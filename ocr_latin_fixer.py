from pycollatinus import Lemmatiseur
import re
import itertools
from lxml.etree import parse, tostring

_match_tags = re.compile("(<.[^(><)]+>)")
_match_words = re.compile("\W")
_match_numbers = re.compile("\D")


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
                        "(\W)("+form+")(\W)",
                        "\g<1><choice><sic>\g<2></sic>{}</choice>\g<3>".format(
                            "".join(["<corr>{}</corr>".format(cor) for cor in proposed])
                        ),
                        line
                    )
                    self.count_changes += 1
                else:
                    print(form + " not recognized")

        return line

    @staticmethod
    def regexp_pattern(form):
        return "(\W)("+form+")(\W)"

    def register_correction(self, fulltext: str):
        """ Marks words that needs to be corrected in a dict

        :param fulltext: XML Text to analyze
        :return: Dict of corrections
        """
        words = _match_tags.sub("", fulltext)
        words = [w for w in _match_words.split(words) if w]
        replacements = {}
        for lemmatisation, form in zip(self.lemmatiseur.lemmatise_multiple(" ".join(words)), words):
            key = Corrector.regexp_pattern(form)
            if len(lemmatisation) == 0 and key not in replacements and _match_numbers.match(form):

                proposed = self.propose_changes(form, []+self.changes)
                if proposed:
                    if len(proposed) == 1:
                        print("Changing " + form + " to " + proposed[0])
                    elif len(proposed) > 1:
                        print("Too much choice for " + form + " : " + ", ".join(proposed))

                    replacements[key] = \
                        "\g<1><choice><sic>\g<2></sic>{}</choice>\g<3>".format(
                            "".join(["<corr>{}</corr>".format(cor) for cor in proposed])
                        )
                    self.count_changes += 1
                else:
                    replacements[key] = "\g<1>\g<2>\g<3>"
                    print(form + " not recognized")

        return replacements

    def propose_changes(self, form: str, changes: list):
        modifications = []
        for source, target in changes:
            cnt = form.count(source)
            if cnt:
                current = []
                for combination in itertools.combinations_with_replacement(target+"_", cnt):
                    if target in combination:  # Makes sure we have at least one replacement
                        original = ""
                        for word_before, replacement in zip(form.split(source), list(combination)+[""]):
                            original += word_before + replacement.replace("_", source)
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

    def xml_corrector(self, path: str, remove=("note", ), root="body"):
        """ This corrector methods removes nodes from text, retrieve words and then replace them

        """
        with open(path) as f:
            original_file = f.read()
        with open(path) as f:
            xml = parse(f)
        clean_up_xml = xml.xpath("//t:"+root, namespaces={"t":"http://www.tei-c.org/ns/1.0"})[0]
        for rem_type in remove:
            for rem_element in clean_up_xml.xpath("//t:"+rem_type, namespaces={"t": "http://www.tei-c.org/ns/1.0"}):
                rem_element.getparent().remove(rem_element)

        for regexp_pattern, regexp_replacements in self.register_correction(tostring(clean_up_xml, encoding=str))\
                    .items():
            original_file = re.sub(regexp_pattern, regexp_replacements, original_file)

        return original_file

if __name__ == "__main__":
    corrector = Corrector(changes=[
        ("s", "a"),
        ("o", "c"),
        ("e", "c")
    ])
    with open("output.xml", "w") as output:
        output.write(corrector.xml_corrector("./full_text.xml"))
    print(str(corrector.count_changes) + " change(s) done")
