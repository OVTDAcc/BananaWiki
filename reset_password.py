#!/usr/bin/env python3
"""
BananaWiki – Admin password-reset tool

Intended to be run over SSH by the server admin:

    python reset_password.py

The tool lists all registered users, lets the admin pick one, then
prompts for (and confirms) a new password before saving it.
"""

import sys
import os
import getpass

# Ensure the project root is on the path when the script is executed from
# a different working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402 – must come after sys.path tweak
import db  # noqa: E402


MIN_PASSWORD_LENGTH = 8


def _print_user_table(users):
    """Print a formatted table of users."""
    print(f"\n{'#':<4} {'ID':<6} {'Username':<24} {'Role':<10} {'Status'}")
    print("-" * 60)
    for idx, user in enumerate(users, start=1):
        status = "suspended" if user["suspended"] else "active"
        print(f"{idx:<4} {user['id']:<6} {user['username']:<24} {user['role']:<10} {status}")
    print()


def main():
    db.init_db()

    users = db.list_users()
    if not users:
        print("No users found in the database.")
        sys.exit(0)

    print("=== BananaWiki Password Reset Tool ===")
    _print_user_table(users)

    # --- user selection ---
    while True:
        raw = input("Enter the number of the user to reset (or 'q' to quit): ").strip()
        if raw.lower() in ("q", "quit", "exit"):
            print("Aborted.")
            sys.exit(0)
        try:
            choice = int(raw)
        except ValueError:
            print("Please enter a valid number.")
            continue
        if 1 <= choice <= len(users):
            selected = users[choice - 1]
            break
        print(f"Please enter a number between 1 and {len(users)}.")

    print(f"\nResetting password for: {selected['username']} (role: {selected['role']})")

    # --- new password ---
    while True:
        new_pw = getpass.getpass("New password: ")
        if len(new_pw) < MIN_PASSWORD_LENGTH:
            print(f"Password must be at least {MIN_PASSWORD_LENGTH} characters. Try again.")
            continue
        confirm_pw = getpass.getpass("Confirm password: ")
        if new_pw != confirm_pw:
            print("Passwords do not match. Try again.")
            continue
        break

    from werkzeug.security import generate_password_hash
    hashed = generate_password_hash(new_pw)
    db.update_user(selected["id"], password=hashed)

    print(f"\nPassword for '{selected['username']}' has been updated successfully.")


if __name__ == "__main__":
    main()
