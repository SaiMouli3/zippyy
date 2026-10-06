// Package docs embeds the OpenAPI document so the API can serve it.
package docs

import _ "embed"

//go:embed openapi.yaml
var OpenAPI []byte
