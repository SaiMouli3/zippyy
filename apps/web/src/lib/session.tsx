import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Role } from '@zippy/shared-types'
import { setSession } from './api'

interface Ctx { role: Role; setRole: (r: Role) => void; theme: 'system' | 'light' | 'dark'; setTheme: (t: 'system' | 'light' | 'dark') => void }
const SessionCtx = createContext<Ctx>({ role: '', setRole: () => {}, theme: 'system', setTheme: () => {} })

// Per-viewer UI preferences only (acting role, theme). Business state always lives in PostgreSQL.
const read = (k: string) => { try { return localStorage.getItem(k) } catch { return null } }
const write = (k: string, v: string) => { try { localStorage.setItem(k, v) } catch { /* private mode */ } }

export function SessionProvider({ children }: { children: ReactNode }) {
  const [role, setRoleState] = useState<Role>((read('zippy.role') as Role) || '')
  const [theme, setThemeState] = useState<'system' | 'light' | 'dark'>((read('zippy.theme') as 'light' | 'dark') || 'system')
  setSession({ role, actor: role ? role.toLowerCase() + '-user' : '' })
  useEffect(() => {
    const el = document.documentElement
    if (theme === 'system') el.removeAttribute('data-theme')
    else el.setAttribute('data-theme', theme)
  }, [theme])
  const value = useMemo<Ctx>(() => ({
    role, theme,
    setRole: r => { setRoleState(r); write('zippy.role', r) },
    setTheme: t => { setThemeState(t); write('zippy.theme', t) },
  }), [role, theme])
  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>
}

export const useSession = () => useContext(SessionCtx)
