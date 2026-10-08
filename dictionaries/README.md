# Bundled dictionaries

LinguaFix ships two kinds of word lists.

## Base — general frequency lists

Top-50k word lists used by `linguafix dict download <lang>`. Each file keeps
only the word column of the upstream list, one word per line.

Source: [FrequencyWords](https://github.com/hermitdave/FrequencyWords) by Hermit
Dave, licensed under the MIT License. The lists are frequency-ordered, so the
first lines are the most common words.

| File | Language |
|---|---|
| `ru-50k.txt` | русский |
| `en-50k.txt` | English |
| `uk-50k.txt` | українська |
| `de-50k.txt` | Deutsch |
| `fr-50k.txt` | français |

## Thematic — professional vocabulary

Domain word lists that widen the detector's vocabulary for a field. They are
**not** bundled in the `.deb`; `linguafix dict install <category>` downloads the
matching archive from the GitHub Release and adds it to the vocabulary on top of
the base list.

| Category | Languages | Files |
|---|---|---|
| `it` | ru, en | `it/ru-it-1k.txt`, `it/en-it-1k.txt` |
| `medicine` | ru, en | `medicine/ru-medicine-1k.txt`, `medicine/en-medicine-1k.txt` |
| `legal` | ru, en | `legal/ru-legal-1k.txt`, `legal/en-legal-1k.txt` |
| `finance` | ru, en | `finance/ru-finance-1k.txt`, `finance/en-finance-1k.txt` |
| `engineering` | ru, en | `engineering/ru-engineering-1k.txt`, `engineering/en-engineering-1k.txt` |
| `science` | ru, en | `science/ru-science-1k.txt`, `science/en-science-1k.txt` |
| `business` | ru, en | `business/ru-business-1k.txt`, `business/en-business-1k.txt` |
| `electronics` | ru, en | `electronics/ru-electronics-1k.txt`, `electronics/en-electronics-1k.txt` |
| `media` | ru, en | `media/ru-media-1k.txt`, `media/en-media-1k.txt` |
| `education` | ru, en | `education/ru-education-1k.txt`, `education/en-education-1k.txt` |
| `gaming` | ru, en | `gaming/ru-gaming-1k.txt`, `gaming/en-gaming-1k.txt` |
| `sport` | ru, en | `sport/ru-sport-1k.txt`, `sport/en-sport-1k.txt` |

Every thematic list is curated by hand for this project and released under the
MIT License (see the repository `LICENSE`); the per-category `README.md` records
the source. No list with an unclear or proprietary licence is included.

## Installing

```bash
linguafix dict categories                     # list categories and languages
linguafix dict install it --lang ru           # download and enable
linguafix dict list-installed                 # what is enabled
linguafix dict remove-category it             # disable
```

Detection priority is **user dictionary → thematic → base → T9**: a word the
user taught wins over everything, a thematic word wins over the general list.
