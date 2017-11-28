from pycollatinus import Lemmatiseur
import re
import itertools
from lxml.etree import parse, tostring
from collections import Counter, defaultdict
from pycollatinus.ch import estRomain as is_roman
from multiprocessing import Pool


_match_tags = re.compile("(<.[^(><)]+>)")
_match_words = re.compile("\W")
_match_numbers = re.compile("\D")


def _zero():
    return 0

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
        self.counter = defaultdict(_zero)
        self.multiprocess = True

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

                proposed = self.letter_swap(form, [] + self.changes)
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

    def split_and_count(self, text: str):
        """ Takes the text, split it into words and count occurences

        :param text: Text
        :return: Words list
        """
        words = _match_tags.sub("", text)
        words = [w for w in _match_words.split(words) if w]
        for key, val in Counter([w.lower() for w in words]).items():
            self.counter[key] = val
        return words

    def sort_proposal(self, words:str):
        """ Given words split around space, returns a score where the lower score will be the best match

        :param words: Words to score
        :return: Score
        """
        rank = 0
        for w in words.split():
            if not is_roman(w):
                rank += self.counter[w]
        return -rank

    def generate_replacement(self, proposed, change_type):
        """ Generate the RegExp replacement value

        :param proposed: List of words
        :param change_type: Type of change
        :return: Replacement value string
        """
        return "\g<1><choice cert=\"medium\" source=\"{}\">><sic>\g<2></sic>{}</choice>\g<3>".format(
            change_type,
            "".join(["<corr>{}</corr>".format(cor) for cor in proposed])
        )

    def register_correction(self, fulltext: str):
        """ Marks words that needs to be corrected in a dict

        :param fulltext: XML Text to analyze
        :return: Dict of corrections
        """
        words = self.split_and_count(fulltext)
        words_next = words[1:] + [""]
        replacements = {}

        for lemmatisation, form, next_tok in zip(
                self.lemmatiseur.lemmatise_multiple(" ".join(words)), words, words_next):

            key = Corrector.regexp_pattern(form)

            if len(lemmatisation) == 0 and key not in replacements and _match_numbers.match(form):
                proposed = self.letter_swap(form, [] + self.changes)

                # If we have a match by simply correcting characters
                if proposed:
                    print(bcolors.OKGREEN + "Changes for " + form + " : " + ", ".join(proposed))
                    proposed = sorted(proposed, key=self.sort_proposal)[:2]
                    replacements[key] = self.generate_replacement(proposed, "OCR-CHARACTER_SWAP")

                else:
                    if len(self.lemmatiseur.lemmatise_multiple(form+next_tok)[0]) > 0:
                        print(bcolors.UNDERLINE + "Gluing " + form + " to " + form+next_tok)
                        replacements[key] = self.generate_replacement([form+next_tok], "OCR-HYPHEN")

                    else:
                        letter_swap = self.letter_swap(form + next_tok, changes=[] + self.changes, raw=False)
                        proposals = [
                            token
                            for token, lemmatisation in zip(letter_swap, self.lemmatiseur.lemmatise_multiple(
                                " ".join(words)
                            ))
                            if len(lemmatisation) > 0
                        ]
                        if len(proposals) > 0:
                            print(bcolors.UNDERLINE + "Gluing " + form + " to " + ", ".join(proposals))
                            proposals = sorted(proposals, key=self.sort_proposal)[:2]
                            replacements[key] = self.generate_replacement(proposals, "OCR-HYPHEN+SWAP")
                        elif self.cutting <= len(form):
                            proposals = [
                                proposal
                                for swap in (self.letter_swap(form, changes=[] + self.changes, raw=False) + [form])
                                for proposal in self.cut_word(swap)
                            ]
                            if len(proposals):
                                proposals = sorted(list(set(proposals)), key=self.sort_proposal)[:2]
                                replacements[key] = self.generate_replacement(proposals, "OCR-AGGLUTINATION")
                                print(bcolors.OKBLUE + form + " was agglutinated : " + ", ".join(proposals))

                if key not in replacements:
                    print(bcolors.FAIL + form + " not recognized")

        return replacements

    def letter_swap(self, form: str, changes: list, raw: bool=False):
        """ Generate swap of letters

        :param form: Original form found in the text
        :param changes: Character Swaps list
        :param raw: Wether or not to return combination filtered by correct lemmatisation
        :return: List of proposals
        """
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
                    for change in self.letter_swap(
                        cur_form,
                        [(src, tgt) for src, tgt in changes if src != source and tgt != target],  # Changes exc. this one
                        raw=raw
                    )
                ]
                modifications += current

        uniques = " ".join(list(set(modifications)))
        if not raw:
            results = [
                new_form
                for new_form, lemmatisations in zip(uniques.split(), self.lemmatiseur.lemmatise_multiple(uniques))
                if len(lemmatisations)
            ]
            return results
        return uniques.split()

    def xml_corrector(self, path: str, remove=("note", ), root="body"):
        """ This corrector methods removes nodes from text, retrieve words and then replace them

        """
        with open(path) as f:
            xml = parse(f)
        clean_up_xml = xml.xpath("//t:"+root, namespaces={"t":"http://www.tei-c.org/ns/1.0"})[0]
        for rem_type in remove:
            for rem_element in clean_up_xml.xpath("//t:"+rem_type, namespaces={"t": "http://www.tei-c.org/ns/1.0"}):
                rem_element.getparent().remove(rem_element)

        text = tostring(clean_up_xml, encoding=str)
        replacements = self.register_correction(text)
        self.count_changes = len(replacements)
        lines = []
        with open(path) as f:
            text_node = False
            for line in f.readlines():
                if "<text" in line:
                    text_node = True
                lines.append((len(lines), line, text_node))

        compiled = []
        for regexp_pattern, regexp_replacements in replacements.items():
            compiled.append((re.compile(regexp_pattern), regexp_replacements))

        line_dict = {}
        if self.multiprocess:
            with Pool(processes=3) as pool:
                for line_index, line in pool.imap_unordered(
                        self.multi_process_replace, [(i, l, t, compiled) for i, l, t in lines]
                ):
                    line_dict[line_index] = line
                    if len(line) % 10 == 0:
                        print("{}/{}".format(len(line_dict), len(lines)))
        else:
            for line_index, line, is_text in lines:
                _, line_dict[line_index] = self.multi_process_replace((line_index, line, is_text, compiled))
                if len(line) % 10 == 0:
                    print("{}/{}".format(len(line_dict), len(lines)))

        return "".join(line_dict[i] for i in range(len(line_dict)))

    def multi_process_replace(self, args):
        index, line, is_text, compiled = args
        if not is_text:
            return index, line
        for regexp_pattern, regexp_replacements in compiled:
            line = regexp_pattern.sub(regexp_replacements, line)
        return index, line

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
    corrector.multiprocess = False
    with open("output.xml", "w") as output:
        output.write(corrector.xml_corrector("./full_text.xml"))
    print(str(corrector.count_changes) + " change(s) done")
