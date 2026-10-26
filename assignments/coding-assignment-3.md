# Coding Assignment 3: Dealing with Newcomers

In this assignment I implemented the `recommend()` function and two new features for newcomers. The features are based on Design Claims from Chapter 5 of *Building Successful Online Communities* (Kraut & Resnick).

| Part | What it does |
|---|---|
| 1. `recommend()` | Shows 5 recommended posts on the "Recommended" tab |
| 2. Welcome new members | Chapter 5, Design Claims 18 and 20 |
| 3. Progressive access | Chapter 5, Design Claim 25 |

## How to run

    docker compose up --build

Open http://127.0.0.1:8000. To see the newcomer features, sign up as a new user. To see the welcome card, log in as an existing user (for example `admin` / `admin`).

---

## Part 1: recommend()

1. Find the posts the user reacted to positively (like, love, haha, wow).
2. Build an "interest profile": the topic words in these posts and how often they appear. Very common words are ignored.
3. Score every other post: shared topic words, +2 if the user follows the author, and up to +3 if the user already liked posts from the same author.
4. Take the 5 posts with the highest score and show them newest first.

The user's own posts and posts they already reacted to are not recommended. With the "Following" filter, only posts from followed users are used. If there is no data about the user yet (cold start), the newest posts are shown.

**Code:** `app.py`: `topic_words()`, `recommend()`

---

## Part 2: Welcome new members

**Design Claim 18 (Chapter 5):** When newcomers have friendly interactions with existing members soon after joining, they stay longer and contribute more.
**Design Claim 20 (Chapter 5):** Assigned welcomers.

- Members who joined in the last 7 days get a **New member 🌱** badge in the feed.
- Existing members see a **Say hello to our new members** card with the latest post of each new member.
- The card has a ready welcome message that can be changed. **Say welcome 👋** posts it as a normal comment, and the new member is removed from the card.

**Code:**
- `app.py`: `inject_newcomer_ids()`, `get_newcomers_to_welcome()`, `feed()`
- `templates/welcome_card.html.j2` (new)
- `templates/feed.html.j2` (card and badge)

---

## Part 3: Progressive access

**Design Claim 25 (Chapter 5):** Progressive access: new accounts earn privileges step by step.

A new account starts at the **Newcomer** level with two limits:
- at most **3 posts per day**
- can follow at most **4 people**

The account becomes a **Member** when it is at least **3 days old** and has written **2 comments**. Then the limits are removed. A **Your access level** card on the feed shows the steps with progress bars and what is still locked. The numbers are constants at the top of the code (`UNLOCK_DAYS`, `UNLOCK_COMMENTS`, `NEWCOMER_POSTS_PER_DAY`, `NEWCOMER_FOLLOW_LIMIT`).

**Code:**
- `app.py`: `account_age_days()`, `get_access_level()`, changes in `add_post()`, `follow_user()` and `feed()`
- `templates/access_card.html.j2` (new)
- `templates/feed.html.j2`

No database changes were needed.