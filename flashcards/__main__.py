from typing import TypedDict

import argparse
import asyncio
import pathlib
import re

import genanki
import tqdm

from flashcards.anki import read_package
from flashcards.sentences import example_sentences, tts


CSS = """
.card {
    font-family: serif;
    font-size: 25px;
    text-align: center;
    color: black;
    background-color: white;
}
"""

class Template(TypedDict):
    name: str
    qfmt: str
    afmt: str


parser = argparse.ArgumentParser()
parser.add_argument("anki_package", type=pathlib.Path)
parser.add_argument("output", type=pathlib.Path)
args = parser.parse_args()

collection = read_package(args.anki_package)


def sentence_template(i: int) -> Template:
    return Template(
        name='Example Sentence %(i)d' % dict(i=i),
        qfmt='{{#Sentence%(i)d}}{{Voice%(i)d}} {{Sentence%(i)d}}{{/Sentence%(i)d}}' % dict(i=i),
        afmt='{{FrontSide}}\n<hr id=answer>\n{{Word}}—{{Meaning}}\n<br>\n{{Translation%(i)d}}' % dict(i=i),
    )


examples_model = genanki.Model(
    1205523417,
    'Word with examples',
    fields=[
        dict(name='Word'),
        dict(name='Meaning'),
        dict(name='Comments'),
        dict(name='Sentence0'),
        dict(name='Voice0'),
        dict(name='Cloze0'),
        dict(name='Conjugation0'),
        dict(name='Translation0'),
        dict(name='Sentence1'),
        dict(name='Voice1'),
        dict(name='Cloze1'),
        dict(name='Conjugation1'),
        dict(name='Translation1'),
        dict(name='Sentence2'),
        dict(name='Voice2'),
        dict(name='Cloze2'),
        dict(name='Conjugation2'),
        dict(name='Translation2'),

    ],
    templates=[
        Template(name='Meaning', qfmt='{{Word}}', afmt='{{FrontSide}}<hr id=answer>{{Meaning}}<br>{{Comments}}'),
        sentence_template(0),
        sentence_template(1),
        sentence_template(2),
    ],
    css=CSS,
)

basic_model = genanki.Model(
    1938227838,
    'Phrase',
    fields=[
        dict(name='Original'),
        dict(name='Voice'),
        dict(name='Translation'),
        dict(name='Comments'),
    ],
    templates=[
        Template(name='Meaning', qfmt='{{Voice}} {{Original}}', afmt='{{FrontSide}}<hr id=answer>{{Translation}}<br>{{Comments}}'),
    ],
    css=CSS,
)


deck = genanki.Deck(1557327995, args.output.stem)
deck.add_model(examples_model)
deck.add_model(basic_model)

media_path = pathlib.Path("media")
media_path.mkdir(exist_ok=True)
media = []

async def make_sentence_note(word, source_note):
    translation = source_note.fields["Translation"]
    comments = source_note.fields["Comments"]

    clozes = await example_sentences(word)

    if not clozes:
        return

    audio_paths = [media_path / f"{word.replace("/", "_")}{i}.mp3" for i in range(3)]
    audio_tasks = []
    for (cloze, _), audio_path in zip(clozes, audio_paths):
        audio_tasks.append(tts(cloze.sentence, audio_path))
    await asyncio.gather(*audio_tasks)

    fields = [word, translation, comments]

    for (cloze, translation), audio_path in zip(clozes, audio_paths):
        media.append(str(audio_path))
        fields.extend((cloze.sentence, f"[sound:{audio_path.name}]", cloze.cloze, ", ".join(cloze.deletions), translation.sentence))
    
    while len(fields) < len(examples_model.fields):
        fields.append("")

    note = genanki.Note(model=examples_model, fields=fields, tags=list(source_note.tags))
    deck.add_note(note)


async def make_phrase_note(source_note):
    original = source_note.fields["Polish original"]
    translation = source_note.fields["Translation"]
    comments = source_note.fields["Comments"]

    audio_path = media_path / f"{original.replace("/", "_")}.mp3"
    await tts(original, audio_path)
    media.append(str(audio_path))

    note = genanki.Note(
        model=basic_model,
        fields=[original, f"[sound:{audio_path.name}]", translation, comments],
        tags=list(source_note.tags),
    )
    deck.add_note(note)


async def make_notes():
    tasks = []

    source_notes = (note for note in collection.notes if "d1" in note.tags)
    sentence_whitelist = {"noun", "particle", "verb", "adjective", "adverb", "conjunction", "preposition", "interjection", "pronoun", "numeral"}
    phrase_whitelist = {"expression", "sentence", "phrase"}

    for source_note in source_notes:
        if (
            sentence_whitelist & source_note.tags
            and (match := re.match(r"(<\w+>)?([\w/]+|\w+(,\s+\w+)*?)(</\w+>)?(\s+\(.*?\))?", source_note.fields["Polish original"]))
            and all(map(lambda word: len(word) - 1, (words := match.group(2).split(", "))))
        ):
            for word in words:
                tasks.append(make_sentence_note(word, source_note))
        elif phrase_whitelist & source_note.tags:
            tasks.append(make_phrase_note(source_note))
        else:
            note = genanki.Note(
                model=basic_model,
                fields=[
                    source_note.fields["Polish original"],
                    "",
                    source_note.fields["Translation"],
                    source_note.fields["Comments"],
                ],
                tags=list(source_note.tags),
            )
            deck.add_note(note)

    bar = tqdm.tqdm(total=len(tasks))

    async with asyncio.TaskGroup() as tg:
        for task in tasks:
            task = tg.create_task(task)
            task.add_done_callback(lambda _: bar.update())


asyncio.run(make_notes())


package = genanki.Package(deck)
package.media_files = media
package.write_to_file(args.output)