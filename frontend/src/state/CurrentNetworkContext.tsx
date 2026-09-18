import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

interface CurrentNetworkValue {
  networkId: string | null
  networkName: string | null
  setCurrentNetwork: (id: string, name: string) => void
  clearCurrentNetwork: () => void
}

const STORAGE_KEY = 'fault-location.current-network'

const CurrentNetworkContext = createContext<CurrentNetworkValue | null>(null)

export function CurrentNetworkProvider({ children }: { children: ReactNode }) {
  const [networkId, setNetworkId] = useState<string | null>(null)
  const [networkName, setNetworkName] = useState<string | null>(null)

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (!raw) return
      const parsed = JSON.parse(raw) as { id?: string; name?: string }
      if (parsed.id) {
        setNetworkId(parsed.id)
        setNetworkName(parsed.name ?? null)
      }
    } catch {
      // Corrupted/blocked storage: fall back to no remembered network.
    }
  }, [])

  function setCurrentNetwork(id: string, name: string) {
    setNetworkId(id)
    setNetworkName(name)
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ id, name }))
    } catch {
      // Best-effort persistence; the in-memory state still works this session.
    }
  }

  function clearCurrentNetwork() {
    setNetworkId(null)
    setNetworkName(null)
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch {
      // ignore
    }
  }

  return (
    <CurrentNetworkContext.Provider value={{ networkId, networkName, setCurrentNetwork, clearCurrentNetwork }}>
      {children}
    </CurrentNetworkContext.Provider>
  )
}

export function useCurrentNetwork(): CurrentNetworkValue {
  const ctx = useContext(CurrentNetworkContext)
  if (!ctx) throw new Error('useCurrentNetwork must be used within CurrentNetworkProvider')
  return ctx
}
