"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Activity, BarChart3, Bot, LayoutDashboard, Settings, TrendingUp } from "lucide-react"
import { cn } from "@/lib/utils"

const NAV = [
  { href: "/", label: "Tổng quan", icon: LayoutDashboard },
  { href: "/markets", label: "Markets", icon: BarChart3 },
  { href: "/agent", label: "Trade Agent", icon: Bot },
  { href: "/vnindex", label: "VNINDEX", icon: TrendingUp },
  { href: "/settings", label: "Cài đặt", icon: Settings },
] as const

export function Sidebar() {
  const pathname = usePathname()
  return (
    <aside className="hidden md:flex w-60 shrink-0 flex-col border-r bg-card/40 px-3 py-4">
      <Link href="/" className="flex items-center gap-2 px-2 pb-4">
        <span className="grid size-8 place-items-center rounded-md bg-primary text-primary-foreground">
          <Activity className="size-4" />
        </span>
        <div className="leading-tight">
          <div className="text-sm font-semibold">TradingAgents</div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">VN dashboard</div>
        </div>
      </Link>
      <nav className="flex flex-col gap-1">
        {NAV.map((item) => {
          const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href))
          const Icon = item.icon
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                active
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
              )}
            >
              <Icon className="size-4" />
              {item.label}
            </Link>
          )
        })}
      </nav>
      <div className="mt-auto pt-4 text-[10px] text-muted-foreground px-2">
        v0.2.5 · {new Date().getFullYear()}
      </div>
    </aside>
  )
}
