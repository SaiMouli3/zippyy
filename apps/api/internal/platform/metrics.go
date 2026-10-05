package platform

import (
	"fmt"
	"sort"
	"sync"
	"time"
)

// Metrics is a tiny in-process counter/latency registry exposed at /api/metrics.
type Metrics struct {
	mu       sync.Mutex
	counters map[string]int64
	lat      map[string]*latency
}

type latency struct {
	count int64
	total time.Duration
	max   time.Duration
}

func NewMetrics() *Metrics { return &Metrics{counters: map[string]int64{}, lat: map[string]*latency{}} }

func key(name string, labels []string) string {
	if len(labels) == 0 {
		return name
	}
	s := name + "{"
	for i := 0; i+1 < len(labels); i += 2 {
		if i > 0 {
			s += ","
		}
		s += fmt.Sprintf("%s=%s", labels[i], labels[i+1])
	}
	return s + "}"
}

func (m *Metrics) Inc(name string, labels ...string) {
	if m == nil {
		return
	}
	m.mu.Lock()
	m.counters[key(name, labels)]++
	m.mu.Unlock()
}

func (m *Metrics) Observe(name string, d time.Duration, labels ...string) {
	if m == nil {
		return
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	k := key(name, labels)
	l := m.lat[k]
	if l == nil {
		l = &latency{}
		m.lat[k] = l
	}
	l.count++
	l.total += d
	if d > l.max {
		l.max = d
	}
}

func (m *Metrics) Get(name string, labels ...string) int64 {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.counters[key(name, labels)]
}

type Snapshot struct {
	Counters  map[string]int64              `json:"counters"`
	Latencies map[string]map[string]float64 `json:"latenciesMs"`
}

func (m *Metrics) Snapshot() Snapshot {
	m.mu.Lock()
	defer m.mu.Unlock()
	s := Snapshot{Counters: map[string]int64{}, Latencies: map[string]map[string]float64{}}
	keys := make([]string, 0, len(m.counters))
	for k := range m.counters {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		s.Counters[k] = m.counters[k]
	}
	for k, l := range m.lat {
		s.Latencies[k] = map[string]float64{"count": float64(l.count), "avg": float64(l.total.Milliseconds()) / float64(l.count), "max": float64(l.max.Milliseconds())}
	}
	return s
}
