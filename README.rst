--------------
gpt-flashcards
--------------

This is a program that adds example sentences and readings from GPT to Anki flashcards.
You'll probably need to edit it to get it to work for you;
the main script relies heavily on the details of the source deck.
Feel free to fork!

If you'd like to use this for target languages other than Polish,
you'll probably need to start by changing the examples in GPT system prompt
in `sentences.py`_

Instructions
------------

Download Per Eriksson's `Polish-English deck`_. Then,

..code:: bash

    export OPENAI_API_KEY=<your-openai-api-key>
    pip install poetry
    poetry install
    poetry run python -m flashcards path/to/Polish-English.apkg GPT-Polish.akpg

You can use `dump.py`_ to dump the contents of an Anki package as CSV files,
which is useful for debugging (it saves you making a round trip to Anki desktop).

..code:: bash

    poetry run python dump.py GPT-Polish.apkg

.. _sentences.py: ./flashcards/sentences.py
.. _Polish-English Deck: https://ankiweb.net/shared/info/3199057698
.. _dump.py: ./dump.py