from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
import collections
import json
import sqlite3
import hashlib
import re
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = '123456789' 
DATABASE = 'database.sqlite'

# Load censorship data
# WARNING! The censorship.dat file contains disturbing language when decrypted. 
# If you want to test whether moderation works, 
# you can trigger censorship using these words: 
# tier1badword, tier2badword, tier3badword
ENCRYPTED_FILE_PATH = 'censorship.dat'
fernet = Fernet('xpplx11wZUibz0E8tV8Z9mf-wwggzSrc21uQ17Qq2gg=')
with open(ENCRYPTED_FILE_PATH, 'rb') as encrypted_file:
    encrypted_data = encrypted_file.read()
decrypted_data = fernet.decrypt(encrypted_data)
MODERATION_CONFIG = json.loads(decrypted_data)
TIER1_WORDS = MODERATION_CONFIG['categories']['tier1_severe_violations']['words']
TIER2_PHRASES = MODERATION_CONFIG['categories']['tier2_spam_scams']['phrases']
TIER3_WORDS = MODERATION_CONFIG['categories']['tier3_mild_profanity']['words']

# ---------------------------------------------------------------
# Coding Assignment 1 - Feature 2: create the table for weekly goals.
# "CREATE TABLE IF NOT EXISTS" only creates it the first time the app starts.
# Each row is one user's goals for one week (week_start = the Monday of that week).
# ---------------------------------------------------------------
with sqlite3.connect(DATABASE) as setup_conn:
    setup_conn.execute('''
        CREATE TABLE IF NOT EXISTS weekly_goals (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            week_start    TEXT    NOT NULL,
            posts_goal    INTEGER NOT NULL,
            comments_goal INTEGER NOT NULL,
            help_goal     INTEGER NOT NULL,
            UNIQUE (user_id, week_start)
        )
    ''')

def get_db():
    """
    Connect to the application's configured database. The connection
    is unique for each request and will be reused if this is called
    again.
    """
    if 'db' not in g:
        g.db = sqlite3.connect(
            DATABASE,
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row

    return g.db


@app.teardown_appcontext
def close_connection(exception):
    """Closes the database again at the end of the request."""
    db = g.pop('db', None)

    if db is not None:
        db.close()


def query_db(query, args=(), one=False, commit=False):
    """
    Queries the database and returns a list of dictionaries, a single
    dictionary, or None. Also handles write operations.
    """
    db = get_db()
    
    # Using 'with' on a connection object implicitly handles transactions.
    # The 'with' statement will automatically commit if successful, 
    # or rollback if an exception occurs. This is safer.
    try:
        with db:
            cur = db.execute(query, args)
        
        # For SELECT statements, fetch the results after the transaction block
        if not commit:
            rv = cur.fetchall()
            return (rv[0] if rv else None) if one else rv
        
        # For write operations, we might want the cursor to get info like lastrowid
        return cur

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return None

@app.template_filter('datetimeformat')
def datetimeformat(value):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    else:
        return "N/A"
    return dt.strftime('%b %d, %Y %H:%M')

REACTION_EMOJIS = {
    'like': '❤️', 'love': '😍', 'laugh': '😂',
    'wow': '😮', 'sad': '😢', 'angry': '😠',
}
REACTION_TYPES = list(REACTION_EMOJIS.keys())


@app.route('/')
def feed():
    #  1. Get Pagination and Filter Parameters 
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    sort = request.args.get('sort', 'new').lower()
    show = request.args.get('show', 'all').lower()
    
    # Define how many posts to show per page
    POSTS_PER_PAGE = 10
    offset = (page - 1) * POSTS_PER_PAGE

    current_user_id = session.get('user_id')
    params = []

    #  2. Build the Query 
    where_clause = ""
    if show == 'following' and current_user_id:
        where_clause = "WHERE p.user_id IN (SELECT followed_id FROM follows WHERE follower_id = ?)"
        params.append(current_user_id)

    # Add the pagination parameters to the query arguments
    pagination_params = (POSTS_PER_PAGE, offset)

    if sort == 'popular':
        query = f"""
            SELECT p.id, p.content, p.created_at, u.username, u.id as user_id,
                   IFNULL(r.total_reactions, 0) as total_reactions
            FROM posts p
            JOIN users u ON p.user_id = u.id
            LEFT JOIN (
                SELECT post_id, COUNT(*) as total_reactions FROM reactions GROUP BY post_id
            ) r ON p.id = r.post_id
            {where_clause}
            ORDER BY total_reactions DESC, p.created_at DESC
            LIMIT ? OFFSET ?
        """
        final_params = params + list(pagination_params)
        posts = query_db(query, final_params)
    elif sort == 'recommended':
        posts = recommend(current_user_id, show == 'following' and current_user_id)
    else:  # Default sort is 'new'
        query = f"""
            SELECT p.id, p.content, p.created_at, u.username, u.id as user_id
            FROM posts p
            JOIN users u ON p.user_id = u.id
            {where_clause}
            ORDER BY p.created_at DESC
            LIMIT ? OFFSET ?
        """
        final_params = params + list(pagination_params)
        posts = query_db(query, final_params)

    posts_data = []
    for post in posts:
        # Determine if the current user follows the poster
        followed_poster = False
        if current_user_id and post['user_id'] != current_user_id:
            follow_check = query_db(
                'SELECT 1 FROM follows WHERE follower_id = ? AND followed_id = ?',
                (current_user_id, post['user_id']),
                one=True
            )
            if follow_check:
                followed_poster = True

        # Determine if the current user reacted to this post and with what reaction
        user_reaction = None
        if current_user_id:
            reaction_check = query_db(
                'SELECT reaction_type FROM reactions WHERE user_id = ? AND post_id = ?',
                (current_user_id, post['id']),
                one=True
            )
            if reaction_check:
                user_reaction = reaction_check['reaction_type']

        reactions = query_db('SELECT reaction_type, COUNT(*) as count FROM reactions WHERE post_id = ? GROUP BY reaction_type', (post['id'],))
        comments_raw = query_db('SELECT c.id, c.content, c.created_at, u.username, u.id as user_id FROM comments c JOIN users u ON c.user_id = u.id WHERE c.post_id = ? ORDER BY c.created_at ASC', (post['id'],))
        post_dict = dict(post)
        post_dict['content'], _ = moderate_content(post_dict['content'])
        comments_moderated = []
        for comment in comments_raw:
            comment_dict = dict(comment)
            comment_dict['content'], _ = moderate_content(comment_dict['content'])
            comments_moderated.append(comment_dict)
                # Coding Assignment 1 - Feature 3: people you follow who reacted to or commented on this post
        followed_engagers = get_followed_engagers(current_user_id, post['id']) if current_user_id else []
        posts_data.append({
            'post': post_dict,
            'followed_engagers': followed_engagers,
            'reactions': reactions,
            'user_reaction': user_reaction,
            'followed_poster': followed_poster,
            'comments': comments_moderated
        })
    # Coding Assignment 1 - Feature 2: data for the weekly goals card (only for logged-in users)
    weekly_goals = get_weekly_goals(current_user_id) if current_user_id else None
    following_activity = get_following_activity(current_user_id) if current_user_id else None
    #  4. Render Template with Pagination Info 
    return render_template('feed.html.j2', 
                           weekly_goals = weekly_goals,
                           following_activity=following_activity,
                           posts=posts_data, 
                           current_sort=sort,
                           current_show=show,
                           page=page, # Pass current page number
                           per_page=POSTS_PER_PAGE, # Pass items per page
                           reaction_emojis=REACTION_EMOJIS,
                           reaction_types=REACTION_TYPES)

@app.route('/posts/new', methods=['POST'])
def add_post():
    """Handles creating a new post from the feed."""
    user_id = session.get('user_id')

    # Block access if user is not logged in
    if not user_id:
        flash('You must be logged in to create a post.', 'danger')
        return redirect(url_for('login'))

    # Get content from the submitted form
    content = request.form.get('content')

    # Pass the user's content through the moderation function
    moderated_content = content
    # Coding Assignment 2: friendly check before posting (Design Claims 23 and 31)
    if content and content.strip():
        review = needs_review('post', content)
        if review:
            return review

    # Basic validation to ensure post is not empty
    if moderated_content and moderated_content.strip():
        db = get_db()
        db.execute('INSERT INTO posts (user_id, content) VALUES (?, ?)',
                   (user_id, moderated_content))
        db.commit()
        flash('Your post was successfully created!', 'success')
    else:
        # This will catch empty posts or posts that were fully censored
        flash('Post cannot be empty or was fully censored.', 'warning')

    # Redirect back to the main feed to see the new post
    return redirect(url_for('feed'))
    
    
@app.route('/posts/<int:post_id>/delete', methods=['POST'])
def delete_post(post_id):
    """Handles deleting a post."""
    user_id = session.get('user_id')

    # Block access if user is not logged in
    if not user_id:
        flash('You must be logged in to delete a post.', 'danger')
        return redirect(url_for('login'))

    # Find the post in the database
    post = query_db('SELECT id, user_id FROM posts WHERE id = ?', (post_id,), one=True)

    # Check if the post exists and if the current user is the owner
    if not post:
        flash('Post not found.', 'danger')
        return redirect(url_for('feed'))

    if post['user_id'] != user_id:
        # Security check: prevent users from deleting others' posts
        flash('You do not have permission to delete this post.', 'danger')
        return redirect(url_for('feed'))

    # If all checks pass, proceed with deletion
    db = get_db()
    # To maintain database integrity, delete associated records first
    db.execute('DELETE FROM comments WHERE post_id = ?', (post_id,))
    db.execute('DELETE FROM reactions WHERE post_id = ?', (post_id,))
    # Finally, delete the post itself
    db.execute('DELETE FROM posts WHERE id = ?', (post_id,))
    db.commit()

    flash('Your post was successfully deleted.', 'success')
    # Redirect back to the page the user came from, or the feed as a fallback
    return redirect(request.referrer or url_for('feed'))

@app.route('/u/<username>')
def user_profile(username):
    """Displays a user's profile page with moderated bio, posts, and latest comments."""
    
    user_raw = query_db('SELECT * FROM users WHERE username = ?', (username,), one=True)
    if not user_raw:
        abort(404)

    user = dict(user_raw)
    moderated_bio, _ = moderate_content(user.get('profile', ''))
    user['profile'] = moderated_bio

    posts_raw = query_db('SELECT id, content, user_id, created_at FROM posts WHERE user_id = ? ORDER BY created_at DESC', (user['id'],))
    posts = []
    for post_raw in posts_raw:
        post = dict(post_raw)
        moderated_post_content, _ = moderate_content(post['content'])
        post['content'] = moderated_post_content
        posts.append(post)

    comments_raw = query_db('SELECT id, content, user_id, post_id, created_at FROM comments WHERE user_id = ? ORDER BY created_at DESC LIMIT 100', (user['id'],))
    comments = []
    for comment_raw in comments_raw:
        comment = dict(comment_raw)
        moderated_comment_content, _ = moderate_content(comment['content'])
        comment['content'] = moderated_comment_content
        comments.append(comment)

    followers_count = query_db('SELECT COUNT(*) as cnt FROM follows WHERE followed_id = ?', (user['id'],), one=True)['cnt']
    following_count = query_db('SELECT COUNT(*) as cnt FROM follows WHERE follower_id = ?', (user['id'],), one=True)['cnt']

    #  NEW: CHECK FOLLOW STATUS 
    is_currently_following = False # Default to False
    current_user_id = session.get('user_id')
    
    # We only need to check if a user is logged in
    if current_user_id:
        follow_relation = query_db(
            'SELECT 1 FROM follows WHERE follower_id = ? AND followed_id = ?',
            (current_user_id, user['id']),
            one=True
        )
        if follow_relation:
            is_currently_following = True
    # --

    return render_template('user_profile.html.j2', 
                           user=user, 
                           posts=posts, 
                           comments=comments,
                           followers_count=followers_count, 
                           following_count=following_count,
                           is_following=is_currently_following)
    

@app.route('/u/<username>/followers')
def user_followers(username):
    user = query_db('SELECT * FROM users WHERE username = ?', (username,), one=True)
    if not user:
        abort(404)
    followers = query_db('''
        SELECT u.username
        FROM follows f
        JOIN users u ON f.follower_id = u.id
        WHERE f.followed_id = ?
    ''', (user['id'],))
    return render_template('user_list.html.j2', user=user, users=followers, title="Followers of")

@app.route('/u/<username>/following')
def user_following(username):
    user = query_db('SELECT * FROM users WHERE username = ?', (username,), one=True)
    if not user:
        abort(404)
    following = query_db('''
        SELECT u.username
        FROM follows f
        JOIN users u ON f.followed_id = u.id
        WHERE f.follower_id = ?
    ''', (user['id'],))
    return render_template('user_list.html.j2', user=user, users=following, title="Users followed by")

@app.route('/posts/<int:post_id>')
def post_detail(post_id):
    """Displays a single post and its comments, with content moderation applied."""
    
    post_raw = query_db('''
        SELECT p.id, p.content, p.created_at, u.username, u.id as user_id
        FROM posts p
        JOIN users u ON p.user_id = u.id
        WHERE p.id = ?
    ''', (post_id,), one=True)

    if not post_raw:
        # The abort function will stop the request and show a 404 Not Found page.
        abort(404)

    #  Moderation for the Main Post 
    # Convert the raw database row to a mutable dictionary
    post = dict(post_raw)
    # Unpack the tuple from moderate_content, we only need the moderated content string here
    moderated_post_content, _ = moderate_content(post['content'])
    post['content'] = moderated_post_content

    #  Fetch Reactions (No moderation needed) 
    reactions = query_db('''
        SELECT reaction_type, COUNT(*) as count
        FROM reactions
        WHERE post_id = ?
        GROUP BY reaction_type
    ''', (post_id,))

    #  Fetch and Moderate Comments 
    comments_raw = query_db('SELECT c.id, c.content, c.created_at, u.username, u.id as user_id FROM comments c JOIN users u ON c.user_id = u.id WHERE c.post_id = ? ORDER BY c.created_at ASC', (post_id,))
    
    comments = [] # Create a new list for the moderated comments
    for comment_raw in comments_raw:
        comment = dict(comment_raw) # Convert to a dictionary
        # Moderate the content of each comment
        print(comment['content'])
        moderated_comment_content, _ = moderate_content(comment['content'])
        comment['content'] = moderated_comment_content
        comments.append(comment)

    # Pass the moderated data to the template
    return render_template('post_detail.html.j2',
                           post=post,
                           reactions=reactions,
                           comments=comments,
                           reaction_emojis=REACTION_EMOJIS,
                           reaction_types=REACTION_TYPES)

@app.route('/about')
def about():
    return render_template('about.html.j2')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html.j2')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        location = request.form.get('location', '')
        birthdate = request.form.get('birthdate', '')
        profile = request.form.get('profile', '')

        hashed_password = generate_password_hash(password)

        db = get_db()
        cur = db.cursor()
        try:
            cur.execute(
                'INSERT INTO users (username, password, location, birthdate, profile) VALUES (?, ?, ?, ?, ?)',
                (username, hashed_password, location, birthdate, profile)
            )
            db.commit()

            # 1. Get the ID of the user we just created.
            new_user_id = cur.lastrowid

            # 2. Add user info to the session cookie.
            session.clear() # Clear any old session data
            session['user_id'] = new_user_id
            session['username'] = username

            # 3. Flash a welcome message and redirect to the feed.
            flash(f'Welcome, {username}! Your account has been created.', 'success')
            return redirect(url_for('feed')) # Redirect to the main feed/dashboard

        except sqlite3.IntegrityError:
            flash('Username already taken. Please choose another one.', 'danger')
        finally:
            cur.close()
            db.close()
            
    return render_template('signup.html.j2')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        db.close()

        # 1. Check if the user exists.
        # 2. If user exists, use check_password_hash to securely compare the password.
        #    This function handles the salt and prevents timing attacks.
        if user and check_password_hash(user['password'], password):
            # Password is correct!
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash('Logged in successfully.', 'success')
            return redirect(url_for('feed'))
        else:
            # User does not exist or password was incorrect.
            flash('Invalid username or password.', 'danger')
            
    return render_template('login.html.j2')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/posts/<int:post_id>/comment', methods=['POST'])
def add_comment(post_id):
    """Handles adding a new comment to a specific post."""
    user_id = session.get('user_id')

    # Block access if user is not logged in
    if not user_id:
        flash('You must be logged in to comment.', 'danger')
        return redirect(url_for('login'))

    # Get content from the submitted form
    content = request.form.get('content')

    # Coding Assignment 2: friendly check before posting (Design Claims 23 and 31)
    if content and content.strip():
        review = needs_review('comment', content, post_id)
        if review:
            return review

    # Basic validation to ensure comment is not empty

    # Basic validation to ensure comment is not empty
    if content and content.strip():
        db = get_db()
        db.execute('INSERT INTO comments (post_id, user_id, content) VALUES (?, ?, ?)',
                   (post_id, user_id, content))
        db.commit()
        flash('Your comment was added.', 'success')
    else:
        flash('Comment cannot be empty.', 'warning')

    # Redirect back to the page the user came from (likely the post detail page).
    # If the comment was sent from the reminder page, go to the post instead.
    if not request.referrer or '/review' in request.referrer:
        return redirect(url_for('post_detail', post_id=post_id))
    return redirect(request.referrer)

@app.route('/comments/<int:comment_id>/delete', methods=['POST'])
def delete_comment(comment_id):
    """Handles deleting a comment."""
    user_id = session.get('user_id')

    # Block access if user is not logged in
    if not user_id:
        flash('You must be logged in to delete a comment.', 'danger')
        return redirect(url_for('login'))

    # Find the comment and the original post's author ID
    comment = query_db('''
        SELECT c.id, c.user_id, p.user_id as post_author_id
        FROM comments c
        JOIN posts p ON c.post_id = p.id
        WHERE c.id = ?
    ''', (comment_id,), one=True)

    # Check if the comment exists
    if not comment:
        flash('Comment not found.', 'danger')
        return redirect(request.referrer or url_for('feed'))

    # Security Check: Allow deletion if the user is the comment's author OR the post's author
    if user_id != comment['user_id'] and user_id != comment['post_author_id']:
        flash('You do not have permission to delete this comment.', 'danger')
        return redirect(request.referrer or url_for('feed'))

    # If all checks pass, proceed with deletion
    db = get_db()
    db.execute('DELETE FROM comments WHERE id = ?', (comment_id,))
    db.commit()

    flash('Comment successfully deleted.', 'success')
    # Redirect back to the page the user came from
    return redirect(request.referrer or url_for('feed'))

@app.route('/react', methods=['POST'])
def add_reaction():
    """Handles adding a new reaction or updating an existing one."""
    user_id = session.get('user_id')

    if not user_id:
        flash("You must be logged in to react.", "danger")
        return redirect(url_for('login'))

    post_id = request.form.get('post_id')
    new_reaction_type = request.form.get('reaction')

    if not post_id or not new_reaction_type:
        flash("Invalid reaction request.", "warning")
        return redirect(request.referrer or url_for('feed'))

    db = get_db()

    # Step 1: Check if a reaction from this user already exists on this post.
    existing_reaction = query_db('SELECT id FROM reactions WHERE post_id = ? AND user_id = ?',
                                 (post_id, user_id), one=True)

    if existing_reaction:
        # Step 2: If it exists, UPDATE the reaction_type.
        db.execute('UPDATE reactions SET reaction_type = ? WHERE id = ?',
                   (new_reaction_type, existing_reaction['id']))
    else:
        # Step 3: If it does not exist, INSERT a new reaction.
        db.execute('INSERT INTO reactions (post_id, user_id, reaction_type) VALUES (?, ?, ?)',
                   (post_id, user_id, new_reaction_type))

    db.commit()

    return redirect(request.referrer or url_for('feed'))

@app.route('/unreact', methods=['POST'])
def unreact():
    """Handles removing a user's reaction from a post."""
    user_id = session.get('user_id')

    if not user_id:
        flash("You must be logged in to unreact.", "danger")
        return redirect(url_for('login'))

    post_id = request.form.get('post_id')

    if not post_id:
        flash("Invalid unreact request.", "warning")
        return redirect(request.referrer or url_for('feed'))

    db = get_db()

    # Remove the reaction if it exists
    existing_reaction = query_db(
        'SELECT id FROM reactions WHERE post_id = ? AND user_id = ?',
        (post_id, user_id),
        one=True
    )

    if existing_reaction:
        db.execute('DELETE FROM reactions WHERE id = ?', (existing_reaction['id'],))
        db.commit()
        flash("Reaction removed.", "success")
    else:
        flash("No reaction to remove.", "info")

    return redirect(request.referrer or url_for('feed'))


@app.route('/u/<int:user_id>/follow', methods=['POST'])
def follow_user(user_id):
    """Handles the logic for the current user to follow another user."""
    follower_id = session.get('user_id')

    # Security: Ensure user is logged in
    if not follower_id:
        flash("You must be logged in to follow users.", "danger")
        return redirect(url_for('login'))

    # Security: Prevent users from following themselves
    if follower_id == user_id:
        flash("You cannot follow yourself.", "warning")
        return redirect(request.referrer or url_for('feed'))

    # Check if the user to be followed actually exists
    user_to_follow = query_db('SELECT id FROM users WHERE id = ?', (user_id,), one=True)
    if not user_to_follow:
        flash("The user you are trying to follow does not exist.", "danger")
        return redirect(request.referrer or url_for('feed'))
        
    db = get_db()
    try:
        # Insert the follow relationship. The PRIMARY KEY constraint will prevent duplicates if you've set one.
        db.execute('INSERT INTO follows (follower_id, followed_id) VALUES (?, ?)',
                   (follower_id, user_id))
        db.commit()
        username_to_follow = query_db('SELECT username FROM users WHERE id = ?', (user_id,), one=True)['username']
        flash(f"You are now following {username_to_follow}.", "success")
    except sqlite3.IntegrityError:
        flash("You are already following this user.", "info")

    return redirect(request.referrer or url_for('feed'))


@app.route('/u/<int:user_id>/unfollow', methods=['POST'])
def unfollow_user(user_id):
    """Handles the logic for the current user to unfollow another user."""
    follower_id = session.get('user_id')

    # Security: Ensure user is logged in
    if not follower_id:
        flash("You must be logged in to unfollow users.", "danger")
        return redirect(url_for('login'))

    db = get_db()
    cur = db.execute('DELETE FROM follows WHERE follower_id = ? AND followed_id = ?',
               (follower_id, user_id))
    db.commit()

    if cur.rowcount > 0:
        # cur.rowcount tells us if a row was actually deleted
        username_unfollowed = query_db('SELECT username FROM users WHERE id = ?', (user_id,), one=True)['username']
        flash(f"You have unfollowed {username_unfollowed}.", "success")
    else:
        # This case handles if someone tries to unfollow a user they weren't following
        flash("You were not following this user.", "info")

    # Redirect back to the page the user came from
    return redirect(request.referrer or url_for('feed'))

@app.route('/admin')
def admin_dashboard():
    """Displays the admin dashboard with users, posts, and comments, sorted by risk."""

    if session.get('username') != 'admin':
        flash("You do not have permission to access this page.", "danger")
        return redirect(url_for('feed'))

    RISK_LEVELS = { "HIGH": 5, "MEDIUM": 3, "LOW": 1 }
    PAGE_SIZE = 50

    def get_risk_profile(score):
        if score >= RISK_LEVELS["HIGH"]:
            return "HIGH", 3
        elif score >= RISK_LEVELS["MEDIUM"]:
            return "MEDIUM", 2
        elif score >= RISK_LEVELS["LOW"]:
            return "LOW", 1
        return "NONE", 0

    # Get pagination and current tab parameters
    try:
        users_page = int(request.args.get('users_page', 1))
        posts_page = int(request.args.get('posts_page', 1))
        comments_page = int(request.args.get('comments_page', 1))
    except ValueError:
        users_page = 1
        posts_page = 1
        comments_page = 1
    
    current_tab = request.args.get('tab', 'users') # Default to 'users' tab

    users_offset = (users_page - 1) * PAGE_SIZE
    
    # First, get all users to calculate risk, then apply pagination in Python
    # It's more complex to do this efficiently in SQL if risk calc is Python-side
    all_users_raw = query_db('SELECT id, username, profile, created_at FROM users')
    all_users = []
    for user in all_users_raw:
        user_dict = dict(user)
        user_risk_score = user_risk_analysis(user_dict['id'])
        risk_label, risk_sort_key = get_risk_profile(user_risk_score)
        user_dict['risk_label'] = risk_label
        user_dict['risk_sort_key'] = risk_sort_key
        user_dict['risk_score'] = min(5.0, round(user_risk_score, 2))
        all_users.append(user_dict)

    all_users.sort(key=lambda x: x['risk_score'], reverse=True)
    total_users = len(all_users)
    users = all_users[users_offset : users_offset + PAGE_SIZE]
    total_users_pages = (total_users + PAGE_SIZE - 1) // PAGE_SIZE

    # --- Posts Tab Data ---
    posts_offset = (posts_page - 1) * PAGE_SIZE
    total_posts_count = query_db('SELECT COUNT(*) as count FROM posts', one=True)['count']
    total_posts_pages = (total_posts_count + PAGE_SIZE - 1) // PAGE_SIZE

    posts_raw = query_db(f'''
        SELECT p.id, p.content, p.created_at, u.username, u.created_at as user_created_at
        FROM posts p JOIN users u ON p.user_id = u.id
        ORDER BY p.id DESC -- Order by ID for consistent pagination before risk sort
        LIMIT ? OFFSET ?
    ''', (PAGE_SIZE, posts_offset))
    posts = []
    for post in posts_raw:
        post_dict = dict(post)
        _, base_score = moderate_content(post_dict['content'])
        final_score = base_score 
        author_created_dt = post_dict['user_created_at']
        author_age_days = (datetime.utcnow() - author_created_dt).days
        if author_age_days < 7:
            final_score *= 1.5
        risk_label, risk_sort_key = get_risk_profile(final_score)
        post_dict['risk_label'] = risk_label
        post_dict['risk_sort_key'] = risk_sort_key
        post_dict['risk_score'] = round(final_score, 2)
        posts.append(post_dict)

    posts.sort(key=lambda x: x['risk_score'], reverse=True) # Sort after fetching and scoring

    # --- Comments Tab Data ---
    comments_offset = (comments_page - 1) * PAGE_SIZE
    total_comments_count = query_db('SELECT COUNT(*) as count FROM comments', one=True)['count']
    total_comments_pages = (total_comments_count + PAGE_SIZE - 1) // PAGE_SIZE

    comments_raw = query_db(f'''
        SELECT c.id, c.content, c.created_at, u.username, u.created_at as user_created_at
        FROM comments c JOIN users u ON c.user_id = u.id
        ORDER BY c.id DESC -- Order by ID for consistent pagination before risk sort
        LIMIT ? OFFSET ?
    ''', (PAGE_SIZE, comments_offset))
    comments = []
    for comment in comments_raw:
        comment_dict = dict(comment)
        _, score = moderate_content(comment_dict['content'])
        author_created_dt = comment_dict['user_created_at']
        author_age_days = (datetime.utcnow() - author_created_dt).days
        if author_age_days < 7:
            score *= 1.5
        risk_label, risk_sort_key = get_risk_profile(score)
        comment_dict['risk_label'] = risk_label
        comment_dict['risk_sort_key'] = risk_sort_key
        comment_dict['risk_score'] = round(score, 2)
        comments.append(comment_dict)

    comments.sort(key=lambda x: x['risk_score'], reverse=True) # Sort after fetching and scoring


    return render_template('admin.html.j2', 
                           users=users, 
                           posts=posts, 
                           comments=comments,
                           
                           # Pagination for Users
                           users_page=users_page,
                           total_users_pages=total_users_pages,
                           users_has_next=(users_page < total_users_pages),
                           users_has_prev=(users_page > 1),

                           # Pagination for Posts
                           posts_page=posts_page,
                           total_posts_pages=total_posts_pages,
                           posts_has_next=(posts_page < total_posts_pages),
                           posts_has_prev=(posts_page > 1),

                           # Pagination for Comments
                           comments_page=comments_page,
                           total_comments_pages=total_comments_pages,
                           comments_has_next=(comments_page < total_comments_pages),
                           comments_has_prev=(comments_page > 1),

                           current_tab=current_tab,
                           PAGE_SIZE=PAGE_SIZE)



@app.route('/admin/delete/user/<int:user_id>', methods=['POST'])
def admin_delete_user(user_id):
    if session.get('username') != 'admin':
        flash("You do not have permission to perform this action.", "danger")
        return redirect(url_for('feed'))
        
    if user_id == session.get('user_id'):
        flash('You cannot delete your own account from the admin panel.', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    db = get_db()
    db.execute('DELETE FROM users WHERE id = ?', (user_id,))
    db.commit()
    flash(f'User {user_id} and all their content has been deleted.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/delete/post/<int:post_id>', methods=['POST'])
def admin_delete_post(post_id):
    if session.get('username') != 'admin':
        flash("You do not have permission to perform this action.", "danger")
        return redirect(url_for('feed'))

    db = get_db()
    db.execute('DELETE FROM comments WHERE post_id = ?', (post_id,))
    db.execute('DELETE FROM reactions WHERE post_id = ?', (post_id,))
    db.execute('DELETE FROM posts WHERE id = ?', (post_id,))
    db.commit()
    flash(f'Post {post_id} has been deleted.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/delete/comment/<int:comment_id>', methods=['POST'])
def admin_delete_comment(comment_id):
    if session.get('username') != 'admin':
        flash("You do not have permission to perform this action.", "danger")
        return redirect(url_for('feed'))

    db = get_db()
    db.execute('DELETE FROM comments WHERE id = ?', (comment_id,))
    db.commit()
    flash(f'Comment {comment_id} has been deleted.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/rules')
def rules():
    return render_template('rules.html.j2')

@app.template_global()
def loop_color(user_id):
    # Generate a pastel color based on user_id hash
    h = hashlib.md5(str(user_id).encode()).hexdigest()
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return f'rgb({r % 128 + 80}, {g % 128 + 80}, {b % 128 + 80})'



# ---------------------------------------------------------------
# Coding Assignment 1 - Feature 1: "Needs a reply"
# Design Claim 1 (Chapter 2): Making the list of needed contributions
# easily visible increases the likelihood that the community will
# provide them.
# This page lists posts that have not received any comment yet,
# so users can easily see where their contribution is needed.
# ---------------------------------------------------------------

@app.route('/unanswered')
def unanswered_posts():
    """Shows posts that nobody has replied to yet."""
    current_user_id = session.get('user_id')

    # Find posts that have no comments at all (newest first).
    # The user's own posts are not shown, because they cannot reply to themselves.
    # If nobody is logged in, -1 is used so no posts are excluded.
    posts_raw = query_db('''
        SELECT p.id, p.content, p.created_at, u.username, u.id AS user_id
        FROM posts p
        JOIN users u ON p.user_id = u.id
        WHERE p.id NOT IN (SELECT post_id FROM comments)
          AND p.user_id != ?
        ORDER BY p.created_at DESC
        LIMIT 20
    ''', (current_user_id or -1,))

    # Run the posts through moderation, like the rest of the site does
    posts = []
    for post_raw in posts_raw:
        post = dict(post_raw)
        post['content'], _ = moderate_content(post['content'])
        posts.append(post)

    return render_template('unanswered.html.j2', posts=posts)


@app.context_processor
def inject_unanswered_count():
    """
    Makes the number of unanswered posts available in every template,
    so it can be shown as a badge next to the "Needs a reply" link in the menu.
    """
    current_user_id = session.get('user_id') or -1
    row = query_db('''
        SELECT COUNT(*) AS cnt
        FROM posts
        WHERE id NOT IN (SELECT post_id FROM comments)
          AND user_id != ?
    ''', (current_user_id,), one=True)
    return {'unanswered_count': row['cnt'] if row else 0}


# ---------------------------------------------------------------
# Coding Assignment 1 - Feature 2: Weekly goals
# Design Claim 13 (Chapter 2): Providing members with specific and highly
# challenging goals, whether self-set or system-suggested, increases contribution.
# Also supports:
#   Design Claim 14: goals with specific deadlines (the week ends on Sunday)
#   Design Claim 15: frequent feedback about performance (progress bars)
# The user sets their own goals for the week, and a card on the feed
# shows their progress towards each goal.
# ---------------------------------------------------------------
def get_week_start(day=None):
    """Returns the Monday (as a datetime at 00:00) of the week that 'day' belongs to."""
    day = day or datetime.utcnow()
    monday = day - timedelta(days=day.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def count_activity(user_id, start, end):
    """
    Counts what a user did between 'start' and 'end':
    posts written, comments written, and "helps"
    (a help = being the FIRST person to comment on someone else's post).
    """
    start_s = start.strftime('%Y-%m-%d %H:%M:%S')
    end_s = end.strftime('%Y-%m-%d %H:%M:%S')

    posts = query_db(
        'SELECT COUNT(*) AS cnt FROM posts WHERE user_id = ? AND created_at >= ? AND created_at < ?',
        (user_id, start_s, end_s), one=True)['cnt']

    comments = query_db(
        'SELECT COUNT(*) AS cnt FROM comments WHERE user_id = ? AND created_at >= ? AND created_at < ?',
        (user_id, start_s, end_s), one=True)['cnt']

    # A comment counts as a "help" if it was the first comment on that post
    # (it has the smallest id of all comments on the post) and the post is not the user's own.
    helps = query_db('''
        SELECT COUNT(*) AS cnt
        FROM comments c
        JOIN posts p ON p.id = c.post_id
        WHERE c.user_id = ? AND c.created_at >= ? AND c.created_at < ?
          AND p.user_id != ?
          AND c.id = (SELECT MIN(id) FROM comments WHERE post_id = c.post_id)
    ''', (user_id, start_s, end_s, user_id), one=True)['cnt']

    return {'posts': posts, 'comments': comments, 'help': helps}


def get_weekly_goals(user_id):
    """Collects everything the goals card on the feed needs for the logged-in user."""
    week_start = get_week_start()
    week_end = week_start + timedelta(days=7)
    last_week_start = week_start - timedelta(days=7)

    # The goals the user set for this week (None if they have not set any yet)
    goals = query_db(
        'SELECT posts_goal, comments_goal, help_goal FROM weekly_goals WHERE user_id = ? AND week_start = ?',
        (user_id, week_start.strftime('%Y-%m-%d')), one=True)

    done = count_activity(user_id, week_start, week_end)          # progress this week
    last_week = count_activity(user_id, last_week_start, week_start)  # shown as a hint

    # One entry per goal type, used to draw the inputs and the progress bars.
    # (Named goal_list, not "items", because "items" would clash with dict.items() in the template.)
    goal_list = []
    for key, icon, label in [('posts', '✍️', 'Posts'),
                             ('comments', '💬', 'Comments'),
                             ('help', '🤝', 'Help unanswered posts')]:
        target = goals[key + '_goal'] if goals else 0
        percent = min(100, int(done[key] * 100 / target)) if target else 0
        goal_list.append({
            'key': key, 'icon': icon, 'label': label,
            'done': done[key], 'target': target, 'percent': percent,
            'reached': target > 0 and done[key] >= target,
            'last_week': last_week[key],
        })

    days_left = (week_end - datetime.utcnow()).days + 1   # deadline countdown (Design Claim 14)
    return {
        'has_goals': goals is not None,
        'goal_list': goal_list,
        'days_left': days_left,
        'all_reached': goals is not None and all(i['reached'] for i in goal_list),
    }


@app.route('/goals', methods=['POST'])
def save_goals():
    """Saves (or updates) the goals the user chose for the current week."""
    user_id = session.get('user_id')
    if not user_id:
        flash('You must be logged in to set goals.', 'danger')
        return redirect(url_for('login'))

    # Read the three numbers from the form. They must be whole numbers from 1 to 50.
    try:
        values = [int(request.form.get(name, 0)) for name in ('posts', 'comments', 'help')]
    except ValueError:
        values = [0]
    if not all(1 <= v <= 50 for v in values):
        flash('Each goal must be a number from 1 to 50.', 'warning')
        return redirect(url_for('feed'))

    # INSERT OR REPLACE: creates the goals, or overwrites them if the user edits them.
    # This works because (user_id, week_start) is UNIQUE in the table.
    week_start = get_week_start().strftime('%Y-%m-%d')
    db = get_db()
    db.execute('''
        INSERT OR REPLACE INTO weekly_goals (user_id, week_start, posts_goal, comments_goal, help_goal)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, week_start, *values))
    db.commit()

    flash('Your goals for this week are saved. Good luck! 🎯', 'success')
    return redirect(url_for('feed'))


# ---------------------------------------------------------------
# Coding Assignment 1 - Feature 3: Activity of people you follow
# Design Claim 15 (Chapter 3): Displaying photos and information about
# individual members and their recent activities promotes bonds-based commitment.
# 1) Under each post in the feed, we show which people you follow reacted to it
#    or commented on it (with a small avatar and a link to their profile).
# 2) A card on the feed lists the latest posts and comments of people you follow.
# ---------------------------------------------------------------
def get_followed_engagers(user_id, post_id):
    """Returns (up to 5) people the user follows who reacted to or commented on the post."""
    rows = query_db('''
        SELECT DISTINCT u.id, u.username
        FROM users u
        WHERE u.id IN (SELECT followed_id FROM follows WHERE follower_id = ?)
          AND (u.id IN (SELECT user_id FROM reactions WHERE post_id = ?)
               OR u.id IN (SELECT user_id FROM comments WHERE post_id = ?))
        LIMIT 5
    ''', (user_id, post_id, post_id))

    # Add an avatar color for each person (loop_color makes the same color for the same user every time)
    return [{'id': r['id'], 'username': r['username'], 'color': loop_color(r['id'])} for r in rows]


def get_following_activity(user_id, limit=5):
    """
    Returns the latest posts and comments written by people the user follows.
    The reactions table has no time column, so only posts and comments can be ordered by time.
    """
    rows = query_db('''
        SELECT 'post' AS kind, p.id AS post_id, u.id AS user_id, u.username, p.content, p.created_at AS created_at
        FROM posts p
        JOIN users u ON u.id = p.user_id
        WHERE p.user_id IN (SELECT followed_id FROM follows WHERE follower_id = ?)

        UNION ALL

        SELECT 'comment' AS kind, c.post_id AS post_id, u.id AS user_id, u.username, c.content, c.created_at AS created_at
        FROM comments c
        JOIN users u ON u.id = c.user_id
        WHERE c.user_id IN (SELECT followed_id FROM follows WHERE follower_id = ?)

        ORDER BY created_at DESC
        LIMIT ?
    ''', (user_id, user_id, limit))

    activity = []
    for row in rows:
        item = dict(row)
        item['content'], _ = moderate_content(item['content'])   # same moderation as the rest of the site
        item['color'] = loop_color(item['user_id'])
        activity.append(item)
    return activity

# ----- Functions to be implemented are below
# Coding Assignment #2


# Assignment 2.2
def user_risk_analysis(user_id):
    """
    Args:
        user_id: The ID of the user on which we perform risk analysis.

    Returns:
        A float risk score for the user, following Rule 2.2 on the /rules page:
        content_risk_score = profile_score * 1 + average_post_score * 3 + average_comment_score * 1,
        then multiplied by 1.5 (account < 7 days old) or 1.2 (account < 30 days old),
        and capped at 5.0.
    """
    user = query_db('SELECT profile, created_at FROM users WHERE id = ?', (user_id,), one=True)
    if not user:
        return 0.0

    # Step 1: score of the profile text
    _, profile_score = moderate_content(user['profile'] or '')

    # Step 2: average score of all posts (0 if the user has no posts)
    posts = query_db('SELECT content FROM posts WHERE user_id = ?', (user_id,))
    post_scores = [moderate_content(p['content'])[1] for p in posts]
    average_post_score = sum(post_scores) / len(post_scores) if post_scores else 0.0

    # Step 3: average score of all comments (0 if the user has no comments)
    comments = query_db('SELECT content FROM comments WHERE user_id = ?', (user_id,))
    comment_scores = [moderate_content(c['content'])[1] for c in comments]
    average_comment_score = sum(comment_scores) / len(comment_scores) if comment_scores else 0.0

    # Step 4: weighted combination (posts count three times as much)
    content_risk_score = (profile_score * 1) + (average_post_score * 3) + (average_comment_score * 1)

    # Step 5: new accounts are riskier, so their score is multiplied
    created_at = user['created_at']
    if isinstance(created_at, str):
        created_at = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
    account_age_days = (datetime.utcnow() - created_at).days if created_at else 9999

    if account_age_days < 7:
        user_risk_score = content_risk_score * 1.5
    elif account_age_days < 30:
        user_risk_score = content_risk_score * 1.2
    else:
        user_risk_score = content_risk_score

    # Step 6: the score can never be higher than 5.0
    return min(user_risk_score, 5.0)


# Regular expressions used by moderate_content().
# A URL is either something that starts with http:// / https:// / www.,
# or a domain name with a common ending (like shopfast.link or example.com), with an optional path.
URL_PATTERN = re.compile(
    r'(?:https?://|www\.)\S+'
    r'|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|co|biz|info|link|xyz|ly|me|app|shop|store|online|site|club|top|click|ru|uk|fi|de|tv|gg)\b(?:/\S*)?',
    re.IGNORECASE
)


def whole_word_pattern(words):
    """Builds ONE case-insensitive regex that matches any of the given words or phrases,
    but only as a whole word (so 'ass' does not match inside 'class').
    Longer words are tried first, so a phrase is matched before a shorter word inside it."""
    escaped = [re.escape(w) for w in sorted(words, key=len, reverse=True)]
    return re.compile(r'(?<!\w)(?:' + '|'.join(escaped) + r')(?!\w)', re.IGNORECASE)


# Build the patterns once when the app starts, instead of on every call (much faster).
TIER1_PATTERN = whole_word_pattern(TIER1_WORDS)
TIER2_PATTERN = whole_word_pattern(TIER2_PHRASES)
TIER3_PATTERN = whole_word_pattern(TIER3_WORDS)


# Assignment 2.1
def moderate_content(content):
    """
    Args
        content: the text content of a post, comment or profile to be moderated.

    Returns:
        A tuple (moderated_content, score), following Part 1 of the /rules page.
    """
    if not content:
        return content, 0.0

    # Stage 1.1: severe violations remove the whole content and give the maximum score
    # Rule 1.1.1: Tier 1 words
    if TIER1_PATTERN.search(content):
        return "[content removed due to severe violation]", 5.0

    # Rule 1.1.2: Tier 2 spam/scam phrases
    if TIER2_PATTERN.search(content):
        return "[content removed due to spam/scam policy]", 5.0

    # Stage 1.2: scored violations, the content is filtered but kept
    moderated_content = content
    score = 0.0

    # Rule 1.2.1: each Tier 3 word is replaced with asterisks of the same length, +2.0 each
    tier3_matches = TIER3_PATTERN.findall(moderated_content)
    if tier3_matches:
        score += 2.0 * len(tier3_matches)
        moderated_content = TIER3_PATTERN.sub(lambda m: '*' * len(m.group(0)), moderated_content)

    # Rule 1.2.2: each URL is replaced with [link removed], +2.0 each
    urls = URL_PATTERN.findall(moderated_content)
    if urls:
        score += 2.0 * len(urls)
        moderated_content = URL_PATTERN.sub('[link removed]', moderated_content)

    # Rule 1.2.3: more than 15 letters and more than 70% of them uppercase, +0.5 (text not changed)
    letters = [ch for ch in content if ch.isalpha()]
    if len(letters) > 15:
        uppercase_ratio = sum(1 for ch in letters if ch.isupper()) / len(letters)
        if uppercase_ratio > 0.7:
            score += 0.5

    return moderated_content, score




#Functions of Assignment 2
# ---------------------------------------------------------------
# Coding Assignment 2 - Design Claim feature: "Friendly check before posting"
# Chapter 4, Design Claim 23: Face-saving ways to correct norm violations increase compliance.
# Chapter 4, Design Claim 31: Graduated sanctions increase the legitimacy and thus the
#                             effectiveness of sanctions.
# Before a post or comment is published, it is checked with moderate_content().
# If it breaks a rule, the user first gets a private, friendly reminder (no public
# punishment) and can fix the text themselves. The reaction is graduated:
#   - small problems (Tier 3 words, links, CAPS): friendly reminder, user may edit or post anyway
#   - severe problems (Tier 1 / Tier 2): the text cannot be published, the user must edit it
# ---------------------------------------------------------------
def check_before_publish(content):
    """Returns the friendly list of problems found in the text, and whether they are severe."""
    moderated, score = moderate_content(content)

    if moderated.startswith('[content removed due to severe violation]'):
        return {'severe': True, 'issues': ['It contains words that are not allowed in our community.']}
    if moderated.startswith('[content removed due to spam/scam policy]'):
        return {'severe': True, 'issues': ['It looks like spam or a scam, which is not allowed here.']}

    issues = []
    if TIER3_PATTERN.search(content):
        issues.append('It contains words that some members may find rude. They will be hidden with *** .')
    if URL_PATTERN.search(content):
        issues.append('It contains a link. Links are removed to protect members from spam.')
    letters = [ch for ch in content if ch.isalpha()]
    if len(letters) > 15 and sum(1 for ch in letters if ch.isupper()) / len(letters) > 0.7:
        issues.append('It is written mostly in CAPITAL LETTERS, which can feel like shouting.')
    return {'severe': False, 'issues': issues}


@app.route('/review')
def review_content():
    """Shows the friendly reminder page for a post or comment that is waiting in the session."""
    pending = session.get('pending')
    if not pending or not session.get('user_id'):
        return redirect(url_for('feed'))

    check = check_before_publish(pending['content'])
    if pending['kind'] == 'comment':
        action = url_for('add_comment', post_id=pending['post_id'])
    else:
        action = url_for('add_post')

    return render_template('review.html.j2',
                           content=pending['content'],
                           preview=moderate_content(pending['content'])[0],
                           issues=check['issues'],
                           severe=check['severe'],
                           kind=pending['kind'],
                           action=action)


@app.route('/review/cancel')
def cancel_review():
    """The user decided not to publish the text."""
    pending = session.pop('pending', None)
    if pending and pending['kind'] == 'comment':
        return redirect(url_for('post_detail', post_id=pending['post_id']))
    return redirect(url_for('feed'))


def needs_review(kind, content, post_id=None):
    """
    Decides if the text must go to the reminder page first.
    Returns a redirect to /review, or None if the text can be published now.
    The user skips the reminder only by clicking "Post anyway" (confirmed=yes),
    and this is never allowed for severe problems.
    """
    check = check_before_publish(content)
    confirmed = request.form.get('confirmed') == 'yes'
    if check['severe'] or (check['issues'] and not confirmed):
        session['pending'] = {'kind': kind, 'content': content, 'post_id': post_id}
        return redirect(url_for('review_content'))
    session.pop('pending', None)
    return None

# Coding Assignment #3
# Assignment 3.1
def recommend(user_id, filter_following):
    """
    Args:
        user_id: The ID of the current user.
        filter_following: Boolean, True if we only want to see recommendations from followed users.

    Returns:
        A list of 5 recommended posts, in reverse-chronological order.

    To test whether your recommendation algorithm works, let's pretend we like the DIY topic. Here are some users that often post DIY comment and a few example posts. Make sure your account did not engage with anything else. You should test your algorithm with these and see if your recommendation algorithm picks up on your interest in DIY and starts showing related content.
    
    Users: @starboy99, @DancingDolphin, @blogger_bob
    Posts: 1810, 1875, 1880, 2113
    
    Materials: 
    - https://www.nvidia.com/en-us/glossary/recommendation-system/
    - http://www.configworks.com/mz/handout_recsys_sac2010.pdf
    - https://www.researchgate.net/publication/227268858_Recommender_Systems_Handbook
    """

    recommended_posts = {} 

    return recommended_posts;

if __name__ == '__main__':
    app.run(debug=True, port=8080)

