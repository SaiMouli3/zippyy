// Package migrations embeds the SQL migration files so the API binary can apply them on boot.
package migrations

import "embed"

//go:embed *.sql
var FS embed.FS
