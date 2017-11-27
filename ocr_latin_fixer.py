from pycollatinus import Lemmatiseur
import re
import itertools

_match_tags = re.compile("(<.[^(><)]+>)")
_match_words = re.compile("\W")


class Corrector:
    """ Declension-Rule Based OCR correct

    :param changes: List of changes that should be done. This list should be a tuple and the where two elements are \
    given, such as `("s", "a")`. s will then be transformed to a
    :type changes: list
    :param lemmatiseur: PyCollatinus Lemmatiseur or any object with a lemmatiseur_multiple method that would returns \
    a list of match for a string of words
    :type lemmatiseur: Lemmatiseur
    """
    def __init__(self, changes: list, lemmatiseur: Lemmatiseur= None):
        if lemmatiseur is None:
            try:
                self.lemmatiseur = Lemmatiseur.load()
            except Exception as E:
                import warnings
                warnings.filterwarnings("ignore")
                print("Loading a lemmatiseur from PyCollatinus")
                self.lemmatiseur = Lemmatiseur()
                self.lemmatiseur.compile()
        self.changes = changes
        self.count_changes = 0

    def read_file(self, path: str):
        """ Read the current file

        :param path: Path to the XML file to correct
        :return: Returns lines
        :rtype: str
        """
        with open(path) as f:
            text_node = False
            lines = ""
            for line in f.readlines():
                if "<text" in line:
                    text_node = True
                if text_node:
                    line = self.correct(line)
                lines += line
        return lines

    def correct(self, line: str):
        words = _match_tags.sub("", line)
        words = [w for w in _match_words.split(words) if w]

        for lemmatisation, form in zip(self.lemmatiseur.lemmatise_multiple(" ".join(words)), words):

            if len(lemmatisation) == 0:

                proposed = self.propose_changes(form, []+self.changes)
                if proposed:
                    if len(proposed) == 1:
                        print("Changing " + form + " to " + proposed[0])
                    elif len(proposed) > 1:
                        print("Too much choice for " + form + " : " + ", ".join(proposed))

                    line = re.sub(
                        "\W("+form+")\W",
                        "<choice><sic>$1</sic>{}</choice>".format("".join("".format(cor) for cor in proposed)),
                        line
                    )
                    self.count_changes += 1
                else:
                    print(form + " not recognized")

        return line

    def propose_changes(self, form: str, changes: list):
        modifications = []
        for source, target in changes:
            cnt = form.count(source)
            if cnt:
                current = []
                for combination in itertools.combinations_with_replacement(target+"_", cnt):
                    if target in combination:  # Makes sure we have at least one replacement
                        original = ""
                        for word_before, replacement in zip(form.split(source), list(combination[0])+[""]):
                            original += word_before + replacement
                        current.append(original)

                current += [
                    change
                    for cur_form in current
                    for change in self.propose_changes(
                        cur_form,
                        [(src, tgt) for src, tgt in changes if src != source and tgt != target]  # Changes exc. this one
                    )
                ]
                modifications += current

        uniques = " ".join(list(set(modifications)))
        return [
            new_form
            for new_form, lemmatisations in zip(uniques.split(), self.lemmatiseur.lemmatise_multiple(uniques))
            if len(lemmatisations)
        ]

if __name__ == "__main__":
    corrector = Corrector(changes=[
        ("s", "a"),
        ("o", "c")
    ])
    with open("output.xml", "w") as output:
        output.write(corrector.read_file("./full_text.xml"))
    print(str(corrector.count_changes) + " change(s) done")
