/** Zustand store for client-only UI state. Server state goes through
 *  TanStack Query — this store is only for things that don't need
 *  refetching across mounts (selected ticker, timeframe, sidebar toggle).
 */
import { create } from "zustand"
import { persist } from "zustand/middleware"

export type Timeframe = "1D" | "1W" | "1M" | "3M" | "1Y"

type UIState = {
  selectedTicker: string
  timeframe: Timeframe
  sidebarCollapsed: boolean
  setSelectedTicker: (t: string) => void
  setTimeframe: (t: Timeframe) => void
  toggleSidebar: () => void
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      selectedTicker: "^VNINDEX",
      timeframe: "1M",
      sidebarCollapsed: false,
      setSelectedTicker: (t) => set({ selectedTicker: t }),
      setTimeframe: (t) => set({ timeframe: t }),
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
    }),
    { name: "dashboard-ui" },
  ),
)
