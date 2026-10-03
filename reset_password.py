"""Teacher tool: reset a student's password (uses the Supabase keys in .env).

    python reset_password.py student@email.com NewPassword123
"""
import sys

from app import auth, db

if len(sys.argv) != 3:
    sys.exit(__doc__)
email, new_pw = sys.argv[1].strip().lower(), sys.argv[2]
user = db.find_user_by_email(email)
if not user:
    sys.exit(f"No account with email {email}")
db.set_password(user["id"], auth.hash_password(new_pw))
print(f"Password reset for {user['name']} <{email}>. Ask them to change it in Settings after logging in.")
