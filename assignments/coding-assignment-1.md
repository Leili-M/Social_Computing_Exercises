# Coding Assignment 1: Contribution and Commitment

In this assignment I added three new features to MiniSocial. Each feature is based on a Design Claim from the book *Building Successful Online Communities* (Kraut & Resnick).

| Feature | Design Claim |
|---|---|
| 1. Needs a reply | Chapter 2, Design Claim 1 |
| 2. Weekly goals | Chapter 2, Design Claim 13 (also 14 and 15) |
| 3. Activity of people you follow | Chapter 3, Design Claim 15 |

## How to run

    docker compose up --build

Then open http://127.0.0.1:8000 and log in.

---

## Feature 1: Needs a reply

**Design Claim (Chapter 2, DC 1):** "Making the list of needed contributions easily visible increases the likelihood that the community will provide them."

A new page shows posts that have no comments yet. You can open it from the "Needs a reply" link in the menu. A red number next to the link shows how many posts are waiting for a reply. Under each post there is a "Be the first to reply" button. After you reply, the post is removed from the list.

**Code:**
- `app.py`: `unanswered_posts()`, `inject_unanswered_count()`
- `templates/unanswered.html.j2` (new)
- `templates/base.html.j2` (menu link)

---

## Feature 2: Weekly goals

**Design Claim (Chapter 2, DC 13):** "Providing members with specific and highly challenging goals, whether self-set or system-suggested, increases contribution."

A "Your goals this week" box at the top of the feed. The user sets their own goals for posts, comments and helping unanswered posts. The box shows a progress bar for each goal, the days left in the week, and a "Goal reached!" message. The goals can be changed with the "Edit my goals" button.

It also follows DC 14 (goals with deadlines) and DC 15 (frequent feedback).

**Code:**
- `app.py`: `get_week_start()`, `count_activity()`, `get_weekly_goals()`, `save_goals()`
- `templates/goals_card.html.j2` (new)
- `templates/feed.html.j2`

**Database:** new table `weekly_goals`. It is created automatically when the app starts.

---

## Feature 3: Activity of people you follow

**Design Claim (Chapter 3, DC 15):** "Displaying photos and information about individual members and their recent activities promotes bonds-based commitment."

Under each post, small avatars show which people you follow reacted to or commented on it. A "Recent activity from people you follow" box shows their latest posts and comments.

**Code:**
- `app.py`: `get_followed_engagers()`, `get_following_activity()`
- `templates/following_activity.html.j2` (new)
- `templates/feed.html.j2`

---

## Other changes

- `Dockerfile`: Python 3.8 → 3.11
- `docker-compose.yml`: the project folder is shared with the container and debug mode is on, so code changes are visible without rebuilding.
