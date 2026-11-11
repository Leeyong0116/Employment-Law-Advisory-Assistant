import { Scale, SquarePen } from 'lucide-react'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar'
import type { HistoryEntry } from '@/state/history'

type AppSidebarProps = {
  entries: HistoryEntry[] // newest first
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
}

// Left sidebar: New question and the browser-only history. One entry per question (plan D2).
// No delete, rename or clear buttons (author's rule 2026-11-01: interface only, no extra features).
export function AppSidebar({ entries, activeId, onSelect, onNew }: AppSidebarProps) {
  const { isMobile, setOpenMobile } = useSidebar()

  function choose(action: () => void) {
    action()
    if (isMobile) setOpenMobile(false) // on a phone the sidebar is a drawer; close it after a choice
  }

  return (
    <Sidebar>
      <SidebarHeader className="gap-3 p-3">
        <div className="flex items-center gap-2 px-2 pt-1">
          <Scale className="size-5" aria-hidden />
          <span className="text-base font-semibold tracking-tight">GetRight</span>
        </div>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton onClick={() => choose(onNew)}>
              <SquarePen aria-hidden />
              <span>New question</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>History</SidebarGroupLabel>
          <nav aria-label="Question history">
            {entries.length === 0 ? (
              <p className="px-2 py-1 text-xs text-sidebar-foreground/60">Your questions will appear here.</p>
            ) : (
              <SidebarMenu>
                {entries.map((entry) => (
                  <SidebarMenuItem key={entry.id}>
                    <SidebarMenuButton
                      isActive={entry.id === activeId}
                      aria-current={entry.id === activeId ? 'page' : undefined}
                      title={entry.query}
                      onClick={() => choose(() => onSelect(entry.id))}
                    >
                      <span className="truncate">{entry.query.slice(0, 60)}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            )}
          </nav>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="p-3">
        <p className="px-2 text-xs leading-5 text-sidebar-foreground/60">
          History is kept in this browser only. Clearing the browser's site data removes it.
        </p>
      </SidebarFooter>
    </Sidebar>
  )
}
