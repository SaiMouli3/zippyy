package domain

import "math"

// Round2 rounds to 2 decimal places (rupees/paise).
func Round2(v float64) float64 { return math.Round(v*100) / 100 }

// Paise converts a rupee amount to integer paise so amounts compare exactly.
func Paise(v float64) int64 { return int64(math.Round(v * 100)) }

// SameAmount reports whether two amounts are identical to the paisa.
func SameAmount(a, b float64) bool { return Paise(a) == Paise(b) }
