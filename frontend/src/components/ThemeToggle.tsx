import { useState } from 'react'
import { Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { applyTheme, initialTheme, type Theme } from '@/lib/theme'

// One button: shows a moon in light mode (go dark) and a sun in dark mode (go light).
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => {
    const start = initialTheme()
    document.documentElement.classList.toggle('dark', start === 'dark')
    return start
  })
  const next: Theme = theme === 'dark' ? 'light' : 'dark'

  function toggle() {
    applyTheme(next)
    setTheme(next)
  }

  return (
    <Button variant="ghost" size="icon-sm" onClick={toggle} aria-label={`Switch to ${next} mode`} title={`Switch to ${next} mode`}>
      {theme === 'dark' ? <Sun aria-hidden /> : <Moon aria-hidden />}
    </Button>
  )
}
