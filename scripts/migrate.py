from codeintent.store import migrate

if __name__ == "__main__":
    migrate()
    print("PostgreSQL schema is ready.")
