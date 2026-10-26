# Coding Assignment 2: Moderation

In this assignment I added moderation tools to MiniSocial: two functions that follow the rules on the `/rules` page, and one new feature based on Design Claims from Chapter 4 of *Building Successful Online Communities* (Kraut & Resnick).

| Part | What it does |
|---|---|
| 1. `moderate_content()` | Censors posts, comments and profiles, and gives each text a risk score |
| 2. `user_risk_analysis()` | Gives each user a risk score, shown in the admin dashboard |
| 3. Friendly check before posting | Chapter 4, Design Claims 23 and 31 |

## How to run

    docker compose up --build

Open http://127.0.0.1:8000. The admin dashboard is at http://127.0.0.1:8000/admin (username `admin`, password `admin`).

To test moderation, use the words `tier1badword`, `tier2badword` and `tier3badword`.

---

## Part 1: moderate_content()

Follows Part 1 of the `/rules` page:

- **Tier 1 words** (severe): the whole text becomes `[content removed due to severe violation]`, score 5.0
- **Tier 2 phrases** (spam/scam): the whole text becomes `[content removed due to spam/scam policy]`, score 5.0
- **Tier 3 words** (mild): each word is replaced with `***`, +2.0 each
- **Links**: each link is replaced with `[link removed]`, +2.0 each
- **Capital letters**: more than 15 letters and more than 70% uppercase, +0.5

All word checks are case-insensitive and match whole words only. The word lists are combined into one regular expression per tier, built once when the app starts, so the admin page stays fast.

**Code:** `app.py`: `moderate_content()`, `whole_word_pattern()`, `URL_PATTERN`

## Part 2: user_risk_analysis()

Follows Rule 2.2 of the `/rules` page:

    content_risk_score = profile_score * 1 + average_post_score * 3 + average_comment_score * 1

Then x1.5 if the account is less than 7 days old, x1.2 if it is less than 30 days old, and capped at 5.0.

**Code:** `app.py`: `user_risk_analysis()`

---

## Part 3: Friendly check before posting

**Design Claims (Chapter 4):**
- **DC 23:** "Face-saving ways to correct norm violations increase compliance."
- **DC 31:** "Graduated sanctions increase the legitimacy and thus the effectiveness of sanctions."

Before a post or comment is published, it is checked with `moderate_content()`. If it breaks a rule, the user sees a private, friendly page ("No big deal! You may not have been aware of our community rules...") that explains the problem and shows what others would see. The user can fix the text themselves.

The reaction is graduated:
- **Small problems** (Tier 3 words, links, capital letters): the user can edit, post anyway (the words are still hidden), or cancel.
- **Severe problems** (Tier 1 / Tier 2): the text cannot be published. The user can only edit or cancel.

**Code:**
- `app.py`: `check_before_publish()`, `needs_review()`, `review_content()` (`/review`), `cancel_review()` (`/review/cancel`), and small changes in `add_post()` and `add_comment()`
- `templates/review.html.j2` (new)

No database changes. The text waiting for review is kept in the session.