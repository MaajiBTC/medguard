class LedgerRouter:
    """Routes the `ledger` app's models to the dedicated `ledger` database, and keeps
    every other app on `default`. This is the actual separation boundary behind
    CLAUDE.md's "store separately from the main application's database" requirement —
    a compromised `default` connection has no path to the ledger tables at all, whether
    the two databases happen to be two local SQLite files (today) or two entirely
    different Postgres providers (once LEDGER_DATABASE_URL points at one).
    """

    route_app_labels = {"ledger"}

    def db_for_read(self, model, **hints):
        return "ledger" if model._meta.app_label in self.route_app_labels else None

    def db_for_write(self, model, **hints):
        return "ledger" if model._meta.app_label in self.route_app_labels else None

    def allow_relation(self, obj1, obj2, **hints):
        db_set = {"default", "ledger"}
        if obj1._state.db in db_set and obj2._state.db in db_set:
            return obj1._state.db == obj2._state.db
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in self.route_app_labels:
            return db == "ledger"
        return db == "default"
