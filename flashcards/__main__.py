from typing import TypedDict, Required

import argparse
import asyncio
import dataclasses
import pathlib
import re
import logging
import sys
import tempfile

import anki
import tqdm

from flashcards.anki import edit_collection, yamlify
from flashcards.sentences import example_sentences, tts


logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
logger.addHandler(handler)
del handler


parser = argparse.ArgumentParser()
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
    default=r"\A\s*(?P<word>\w+)\s*\Z",
    help="Regular expression (python syntax) for extracting the word from the field."
    " Should have a group named `word`, e.g. " r"\A\s*(?P<word>\w+)\s*\Z",
)
parser.add_argument(
    "--include-tags",
    nargs="+",
    help="filter in notes with these tags.",
)
parser.add_argument(
    "--exclude-tags",
    nargs="+",
    default=None,
    help="Filter out notes with these tags."
)
parser.add_argument(
    "-n", "--n-sentences",
    type=int,
    default=1,
    help="Number of sentences to generate per card."
)
args = parser.parse_args()

if args.very_verbose:
    logger.setLevel(logging.DEBUG)
elif args.verbose:
    logger.setLevel(logging.INFO)
else:
    logger.setLevel(logging.WARNING)

with edit_collection(args.package) as col:
    logger.info(f"{len(col.models.all())} models: " + ", ".join(m['name'] for m in col.models.all()))
    logger.info(
        f"{len(col.decks.all())} decks: "
        + ", ".join(d['name'] for d in col.decks.all())
    )

    def predicate(model) -> bool:
        return (
            model['name'].casefold() == args.model.casefold()
            and args.word_field in {fld['name'] for fld in model['flds']}
        )

    try:
        source_model = next(iter(filter(predicate, col.models.all())))
    except StopIteration:
        logger.fatal("Could not find model %s in package.", args.model)
        sys.exit(1)

    if args.deck_name is None:
        def predicate(deck) -> bool:
            return deck['name'].casefold() != "default"

        try:
            source_deck = next(iter(filter(predicate, col.decks.all())))
        except StopIteration:
            source_deck = next(iter(col.decks.all()))
    else:
        def predicate(deck) -> bool:
            return deck['name'].casefold() == args.deck_name.casefold()

        try:
            source_deck = next(iter(filter(predicate, col.decks.all())))
        except StopIteration:
            logger.fatal("Could not find deck %s in package.", args.deck_name)
            sys.exit(1)

    def add_field_idempotent(name: str) -> None:
        for fld in source_model["flds"]:
            if fld["name"] == name:
                break
        else:
            col.models.addField(source_model, dict(name=name))

    if not args.dry_run:
        for i in range(args.n_sentences):
            add_field_idempotent(f"Sentence{i}")
            add_field_idempotent(f"SentenceTranslation{i}")
            add_field_idempotent(f"Voice{i}")

    def update_note(source_note, sentences):
        for i, (sentence, translation, voice) in sentences:
            logger.info("adding sentence {sentence!r} {translation!r} to {word!r}")
            source_note[f"Sentence{i}"] = sentence
            source_note[f"SentenceTranslation{i}"] = translation
            source_note[f"Voice{i}"] = f"[sound:{voice.name}]"
            col.media.add_file(voice)

        col.update_note(source_note)
    
    media_path = pathlib.Path("media")

    async def make_sentence_note(word, source_note):
        clozes = await example_sentences(word)
        if not clozes:
            return

        audio_paths = [media_path / f"{word.replace("/", "_")}{i}.mp3" for i in range(args.n_sentences)]
        audio_tasks = []
        for (cloze, _), audio_path in zip(clozes, audio_paths):
            audio_tasks.append(tts(cloze.sentence, audio_path))
        await asyncio.gather(*audio_tasks)

        sentences = [
            (cloze.sentence, translation, audio_path)
            for (cloze, translation), audio_path in zip(clozes, audio_paths)
        ]
        update_note(source_note, sentences)

    word_re = re.compile(args.word_regex)
    html_re = re.compile(r"<[^>]+?>")

    async def make_notes():
        tasks = []

        whitelist = set(args.include_tags) if args.include_tags else set()
        blacklist = set(args.exclude_tags) if args.exclude_tags else set()

        for nid in col.find_notes(""):
            source_note = col.get_note(nid)
            tags = set(source_note.tags)
            if (
                source_note.mid == source_model["id"]
                and (not args.include_tags or whitelist & tags)
                and not blacklist & tags
            ):
                value = source_note[args.word_field]
                value = html_re.sub("", value)
                if (match := word_re.match(value)):
                    word = match.group("word")

                    if args.dry_run:
                        logger.debug(f"would add sentences to {word!r}")
                    else:
                        tasks.append(make_sentence_note(word, source_note))
                else:
                    logger.error(f"source field value {value!r} did not match regex {word_re!r}")
                    logger.error(yamlify(source_note))
                    sys.exit(1)

        bar = tqdm.tqdm(total=len(tasks))

        async with asyncio.TaskGroup() as tg:
            for task in tasks:
                task = tg.create_task(task)
                task.add_done_callback(lambda _: bar.update())

    asyncio.run(make_notes())