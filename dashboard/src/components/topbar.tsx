"use client"

import { Menu } from "lucide-react"
import { ThemeToggle } from "@/components/theme-toggle"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetTrigger,
  SheetTitle,
  SheetHeader,
} from "@/components/ui/sheet"
import { Sidebar } from "@/components/sidebar"

export function Topbar() {
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-background/80 px-4 backdrop-blur">
      <Sheet>
        <SheetTrigger
          render={
            <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open menu">
              <Menu className="size-5" />
            </Button>
          }
        />
        <SheetContent side="left" className="p-0 w-64">
          <SheetHeader className="sr-only">
            <SheetTitle>Navigation</SheetTitle>
          </SheetHeader>
          <Sidebar />
        </SheetContent>
      </Sheet>
      <div className="flex-1" />
      <div className="hidden sm:flex items-center gap-2 text-xs text-muted-foreground tabular">
        <span className="inline-flex size-2 rounded-full bg-[color:var(--bullish)] animate-pulse" />
        Live · {new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })}
      </div>
      <ThemeToggle />
    </header>
  )
}
