from typing import TypedDict, Required

import argparse
import asyncio
import pathlib
import re
import logging
import sys

import genanki
import tqdm

from flashcards.anki import read_package
from flashcards.sentences import example_sentences, tts


html_re = re.compile(r"<[^>]+?>")

def strip_html(s: str) -> str:
    return html_re.sub("", s)


ruby_re = re.compile(r"\[[^\]]+?\]")

def strip_ruby(s: str) -> str:
    return ruby_re.sub("", s)


logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
logger.addHandler(handler)
del handler


parser = argparse.ArgumentParser()
parser.add_argument(
    "prompt_file",
    type=pathlib.Path,
    help="Path to file containing the prompt for GPT."
)
parser.add_argument(
    "package",
    type=pathlib.Path,
    help="Path to source anki deck.",
)
parser.add_argument("out", type=pathlib.Path)
parser.add_argument("-v", "--verbose", action="store_true")
parser.add_argument("-vv", "--very-verbose", action="store_true")
parser.add_argument("--dry-run", action="store_true")
parser.add_argument(
    "--deck-name",
    help="Name of the deck to add sentences and readings to."
    " If left blank, defaults to the first deck in the package not named Default,"
    " unless there is only one deck in the package in which case we use that deck.",
)
parser.add_argument(
    "--model",
    default="Basic",
    help="Name of the note type to add sentences and readings to.",
)
parser.add_argument(
    "--word-field",
    default="Front",
    help="Name of the field to use as a source for vocabulary words.",
)
parser.add_argument(
    "--word-regex",
    default=r"\A\s*(?P<word>.+?)\s*\Z",
    help="Regular expression (python syntax) for extracting the word from the field."
    " Should have a group named `word`, e.g. " r"\A\s*(?P<word>\w+)\s*\Z",
)
parser.add_argument(
    "--meaning-field",
    default="Back",
    help="Name of the field to use as a source for the meanings of words.",
)
parser.add_argument(
    "--meaning-regex",
    default=r"\A\s*(?P<meaning>.+?)\s*\Z",
    help="Regular expression (python syntax) for extracting the word from the field."
    " Should have a group named `meaning`, e.g. " r"\A\s*(?P<meaning>\w+)\s*\Z",
)
parser.add_argument(
    "--sentence-field",
    default="Sentence",
    help="Name of the field to replace with the generated sentence.",
)
parser.add_argument(
    "--translation-field",
    default="SentenceTranslation",
    help="Name of the field to replace with the generated translation.",
)
parser.add_argument(
    "--tts-field",
    default="Voice",
    help="Name of the field to replace with the generated tts.",
)
parser.add_argument(
    "--include-tags",
    nargs="+",
    default=None,
    help="filter in notes with these tags.",
)
parser.add_argument(
    "--exclude-tags",
    nargs="+",
    default=[],
    help="Filter out notes with these tags."
)

args = parser.parse_args()

if args.very_verbose:
    logger.setLevel(logging.DEBUG)
elif args.verbose:
    logger.setLevel(logging.INFO)
else:
    logger.setLevel(logging.WARNING)


collection = read_package(args.package)

logger.info(f"{len(collection.models)} models: " + ", ".join(m.name for m in collection.models))
logger.info(f"{len(collection.decks)} decks: " + ", ".join(d.name for d in collection.decks))
logger.info(f"{len(collection.notes)} notes")

def predicate(model) -> bool:
    field_names = {f.name for f in model.fields}
    return (
        model.name.casefold() == args.model.casefold()
        and args.word_field in field_names
        and args.meaning_field in field_names
        and args.sentence_field in field_names
        and args.translation_field in field_names
        and args.tts_field in field_names
    )

try:
    source_model = next(iter(filter(predicate, collection.models)))
except StopIteration:
    logger.fatal(
        "Could not find model %s with required fields %s in package.",
        args.model,
        ", ".join((args.word_field, args.meaning_field, args.sentence_field, args.translation_field, args.tts_field)),
    )
    sys.exit(1)

if args.deck_name is None:
    def predicate(deck) -> bool:
        return deck.name.casefold() != "default"

    try:
        source_deck = next(iter(filter(predicate, collection.decks)))
    except StopIteration:
        source_deck = next(iter(collection.decks))
else:
    def predicate(deck) -> bool:
        return deck.name.casefold() == args.deck_name.casefold()

    try:
        source_deck = next(iter(filter(predicate, collection.decks)))
    except StopIteration:
        logger.fatal("Could not find deck %s in package.", args.deck_name)
        sys.exit(1)


logger.info(f"Reusing id {source_model.id!r} from model {source_model.name!r}")
model = genanki.Model(
    model_id=source_model.id,
    name=source_model.name,
    fields=[f.to_anki2() for f in source_model.fields],
    templates=[t.to_anki2() for t in source_model.templates],
    css=source_model.css,
    latex_pre=source_model.latex_pre,
    latex_post=source_model.latex_post,
)

logger.info(f"Reusing id {source_deck.id!r} from deck {source_deck.name!r}")
deck = genanki.Deck(
    deck_id=source_deck.id,
    name=source_deck.name, 
    description=source_deck.description,
)
deck.add_model(model)

media_path = pathlib.Path("media")
media_files = []

def update_note(source_note, sentence, translation, voice):
    sort_field = source_note.field_values[source_note.model.sort_field]
    logger.debug(f"adding sentence {sentence!r} {translation!r} to {sort_field!r}")
    media_files.append(voice)

    fields = []
    for name, value in source_note.fields.items():
        if name == args.sentence_field:
            fields.append(sentence)
        elif name == args.translation_field:
            fields.append(translation)
        elif name == args.tts_field:
            fields.append(f'[sound:{voice.name}]')
        else:
            fields.append(value)

    note = genanki.Note(
        model=model,
        fields=fields,
        tags=source_note.tags,
        guid=source_note.guid,
    )
    deck.add_note(note)

with open(args.prompt_file) as f:
    prompt = f.read()

async def make_sentence_note(word, meaning, source_note):
    (cloze, translation), *_ = await example_sentences(prompt, f"{word} ({meaning})")

    safe_word = strip_ruby(strip_html(word)).translate({"/": "_", ":": "_"})
    audio_path = media_path / f"{safe_word}.mp3"
    await tts(cloze.sentence, audio_path)

    update_note(source_note, cloze.sentence, translation.sentence, audio_path)

word_re = re.compile(args.word_regex)
meaning_re = re.compile(args.meaning_regex)

async def make_notes():
    tasks = []

    whitelist = set(args.include_tags) if args.include_tags else set()
    blacklist = set(args.exclude_tags)

    for source_note in collection.notes[:1]:
        tags = set(source_note.tags)
        if (
            source_note.model.id == source_model.id
            and (not args.include_tags or whitelist & tags)
            and not blacklist & tags
        ):
            word_value = strip_html(source_note.fields[args.word_field])
            if not (word_match := word_re.match(word_value)):
                logger.error(f"word field value {word_value!r} did not match regex {word_re!r}")
                sys.exit(1)
            
            meaning_value = strip_html(source_note.fields[args.meaning_field])
            if not (meaning_match := meaning_re.match(meaning_value)):
                logger.error(f"meaning field value {meaning_value!r} did not match regex {meaning_re!r}")
                sys.exit(1)

            word = word_match.group("word")
            meaning = meaning_match.group("meaning")
            tasks.append(make_sentence_note(word, meaning, source_note))

    bar = tqdm.tqdm(total=len(tasks))

    async with asyncio.TaskGroup() as tg:
        for task in tasks:
            task = tg.create_task(task)
            task.add_done_callback(lambda _: bar.update())

asyncio.run(make_notes())

package = genanki.Package([deck])
package.media_files = media_files
package.write_to_file(args.out)