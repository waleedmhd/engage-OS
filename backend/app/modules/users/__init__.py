"""User / role management (Settings & Administration — piece 3).

Admin-only CRUD over the `users` table. The `User` model lives in
`app.modules.auth.models` and is re-exported from `.models` here so this
module is the public surface for user administration without duplicating
the ORM definition.
"""
