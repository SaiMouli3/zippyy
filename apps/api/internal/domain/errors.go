package domain

import (
	"errors"
	"fmt"
	"net/http"
)

// AppError is the single error type the HTTP layer knows how to render.
type AppError struct {
	Status  int            `json:"-"`
	Code    string         `json:"code"`
	Message string         `json:"message"`
	Details map[string]any `json:"details,omitempty"`
}

func (e *AppError) Error() string { return fmt.Sprintf("%s: %s", e.Code, e.Message) }

func NewError(status int, code, msg string) *AppError {
	return &AppError{Status: status, Code: code, Message: msg}
}

func (e *AppError) With(k string, v any) *AppError {
	cp := *e
	cp.Details = map[string]any{}
	for kk, vv := range e.Details {
		cp.Details[kk] = vv
	}
	cp.Details[k] = v
	return &cp
}

func Validation(msg string, fields map[string]string) *AppError {
	e := NewError(http.StatusUnprocessableEntity, "VALIDATION_FAILED", msg)
	if len(fields) > 0 {
		e.Details = map[string]any{"fields": fields}
	}
	return e
}

func NotFound(what string) *AppError {
	return NewError(http.StatusNotFound, "NOT_FOUND", what+" not found")
}

func Conflict(code, msg string) *AppError { return NewError(http.StatusConflict, code, msg) }

func Forbidden(msg string) *AppError { return NewError(http.StatusForbidden, "FORBIDDEN", msg) }

// AsAppError unwraps err into an *AppError when possible.
func AsAppError(err error) (*AppError, bool) {
	var ae *AppError
	if errors.As(err, &ae) {
		return ae, true
	}
	return nil, false
}
