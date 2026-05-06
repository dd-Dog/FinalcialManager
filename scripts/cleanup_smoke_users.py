import os

import psycopg


def main() -> None:
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres123@localhost:5432/financial_manager",
    )
    user_prefix = os.getenv("SMOKE_USER_PREFIX", "smoke")
    username_pattern = f"{user_prefix}_%"

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH target_users AS (
                  SELECT id FROM users WHERE username LIKE %s
                )
                DELETE FROM income_expense_tags WHERE user_id IN (SELECT id FROM target_users);
                DELETE FROM transfer_records WHERE user_id IN (SELECT id FROM target_users);
                DELETE FROM positions WHERE user_id IN (SELECT id FROM target_users);
                DELETE FROM transactions WHERE user_id IN (SELECT id FROM target_users);
                DELETE FROM assets WHERE user_id IN (SELECT id FROM target_users);
                DELETE FROM accounts WHERE user_id IN (SELECT id FROM target_users);
                DELETE FROM users WHERE id IN (SELECT id FROM target_users);
                """,
                (username_pattern,),
            )
        conn.commit()
    print(f"cleanup complete for users like: {username_pattern}")


if __name__ == "__main__":
    main()
