--------------
gpt-flashcards
--------------

This is a program that adds example sentences and readings from GPT to Anki flashcards.
You'll probably need to edit it to get it to work for you;
the main script relies heavily on the details of the source deck.
Feel free to fork!

If you'd like to use this for target languages other than Polish or Japanese
you'll probably need to start by writing a new prompt.

Here's an example sentence for the Polish word "angielski":
    
   Chciałbym zamówić książkę do nauki języka {angielskiego}.

   I would like to order a book for learning the {English language}.
   
   `Generated audio`__

__ ./media/angielski0.mp3

And another for the Japanese word "帆[はん] 船[せん] (sailing ship)":

   昔の人々は{帆船}を使って大海原を冒険した。"

   In the old days, people used {sailing ships} to adventure across the vast oceans.
   
   `Generated audio`__

__ ./media/帆船.mp3

It cost me about 5 USD in OpenAI credits to debug this program and generate examples for
the ~1000 cards tagged d1 in the `Polish-English deck`_.

Instructions
------------

Right now the program is set up to add a sentence, translation and reading to
*cards that already exist*.

Start by adding three fields to the note type for the notes you want to modify.
The default names are ``Sentence``, ``SentenceTranslation`` and ``Voice``.
You'll have to do this the Anki desktop app or similar.
Export the deck as a ``.apkg``. Then

.. code:: bash

    export OPENAI_API_KEY=<your-openai-api-key>
    pip install poetry
    poetry install
    poetry run python -m flashcards \
        prompts/japanese.txt \
        path/to/export.apkg \
        WithGPT.akpg \
        --model NameOfNoteType \
        --word-field NameOfWordField \
        --meaning-field NameOfMeaningField

Then reimport the deck into Anki, and it should update all the old cards
(without destroying the scheduling infortmation).
You'll have to edit the card templates to get the sentences to show up in reviews.

You can select a GPT model with ``--gpt-version``.
I've tried ``gpt-4-1106-preview`` and ``gpt-3.5-turbo-instruct``.
GPT 4 worked fine for Polish,
but for some reason for Japanese it was much more expensive
(probably Japanese sentences require more tokens)
and worse at generating sentences in the correct format.
For Japanese, ``gpt-3.5-turbo-instruct`` worked better.

You can use `dump.py`_ to dump the contents of an Anki package as CSV files,
which is useful for debugging (it saves you making a round trip to Anki desktop).

.. code:: bash

    poetry run python dump.py WithGPT.apkg

.. _sentences.py: ./flashcards/sentences.py
.. _Polish-English Deck: https://ankiweb.net/shared/info/3199057698
.. _dump.py: ./dump.py
