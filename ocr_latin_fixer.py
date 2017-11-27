from pycollatinus import Lemmatiseur
import re
import itertools
from lxml.etree import parse, tostring

_match_tags = re.compile("(<.[^(><)]+>)")
_match_words = re.compile("\W")
_match_numbers = re.compile("\D")


class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


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
        self.cutting = True

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
        words_next = words[1:] + [""]
        replacements = {}
        curr_remove = False
        for lemmatisation, form, next_tok \
            in zip(self.lemmatiseur.lemmatise_multiple(" ".join(words)), words, words_next):
            key = Corrector.regexp_pattern(form)

            if curr_remove:
                replacements[key] = \
                    "\g<1><choice cert=\"high\" source=\"OCR-LINECUT\"><sic>\g<2></sic><corr></corr></choice>\g<3>"
                curr_remove = False

            elif len(lemmatisation) == 0 and key not in replacements and _match_numbers.match(form):

                proposed = self.propose_changes(form, []+self.changes)
                if proposed:
                    if len(proposed) == 1:
                        print(bcolors.OKGREEN + "Changing " + form + " to " + proposed[0])
                    elif len(proposed) > 1:
                        print(bcolors.OKGREEN + "Too much choice for " + form + " : " + ", ".join(proposed))

                    replacements[key] = \
                        "\g<1><choice cert=\"medium\" source=\"OCR-CHARACTER-SWAP\">><sic>\g<2></sic>{}</choice>\g<3>".format(
                            "".join(["<corr>{}</corr>".format(cor) for cor in proposed])
                        )
                    self.count_changes += 1

                elif len(self.lemmatiseur.lemmatise_multiple(form + next_tok)[0]) > 0:
                    print(bcolors.UNDERLINE + "Gluing " + form + " to " + form + next_tok)
                    replacements[key] = \
                        "\g<1><choice cert=\"high\" source=\"OCR-LINECUT\">><sic>\g<2></sic><corr>{}</corr></choice>\g<3>".format(
                            form+next_tok
                        )
                    curr_remove = True
                    self.count_changes += 1
                elif self.cutting <= len(form):
                    proposals = self.cut_word(form)
                    if len(proposals):
                        replacements[key] = \
                            "\g<1><choice cert=\"low\" source=\"OCR-AGGLUTINATION\"><sic>\g<2></sic>{}</choice>\g<3>".format(
                                "".join(["<corr>{}</corr>".format(cor) for cor in proposals])
                            )

                        self.count_changes += 1
                        print(bcolors.OKBLUE + form + " was agglutinated : " + ", ".join(proposals))
                    else:
                        replacements[key] = "\g<1>\g<2>\g<3>"
                        print(bcolors.FAIL + form + " not recognized")
                else:
                    replacements[key] = "\g<1>\g<2>\g<3>"
                    print(bcolors.FAIL + form + " not recognized")

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

    def subwords(self, form: str):
        """ Tries to find for a given token possible cuts

        :param form: Original token
        :type form: str
        :return: List of possible match
        """
        if len(form) == 0:
            return []

        proposals = []
        for i in range(1, len(form)):
            start, end = form[:i], form[i:]
            exists = [len(analysis) > 0 for analysis in self.lemmatiseur.lemmatise_multiple(start+" "+end)]
            if False not in exists:
                proposals.append(start+" "+end)
            if exists[0] is True and exists[1] is False:
                proposals += [start+" "+subproposal for subproposal in self.subwords(end)]

        return proposals

    def cut_word(self, form: str):
        """ Tries to find for a given token possible cuts

        :param form: Original token
        :type form: str
        :return: List of possible match
        """
        proposals = sorted(self.subwords(form), key=lambda x: len(x.split()))
        if len(proposals) == 0:
            return []
        minimal_len = len(proposals[0].split())
        return [p for p in proposals if len(p.split()) == minimal_len]

if __name__ == "__main__":
    corrector = Corrector(changes=[
        ("s", "a"),
        ("o", "c"),
        ("c", "o"),
        ("e", "c"),
        ("l", "I")
    ])
    # Test that checks we have not broken things
    assert corrector.cut_word("quiaadextris") == ["quia a dextris"]
    corrector.cutting = 5  # Set to false for real output as cutting seems to change too much !
    # Launch !
    with open("output.xml", "w") as output:
        output.write(corrector.xml_corrector("./full_text.xml"))
    print(str(corrector.count_changes) + " change(s) done")
