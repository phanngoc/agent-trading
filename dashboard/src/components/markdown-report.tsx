"use client"

import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"

/** Render an LLM agent report as styled markdown.
 *
 *  The reports embed:
 *    - ATX headings up to ###/####
 *    - GFM tables (Market Analyst leans heavily on these)
 *    - bullet lists, bold/italic emphasis
 *    - occasional inline code for tickers and `boll_ub`-style indicators
 *
 *  We don't pull in @tailwindcss/typography because tailwind v4 hasn't
 *  shipped a stable preset for it yet; styling each element directly
 *  with `components={...}` is more predictable and lets us match the
 *  dashboard's compact density.
 */
export function MarkdownReport({ content, className }: { content: string; className?: string }) {
  if (!content) {
    return <p className="text-sm text-muted-foreground italic">— Không có dữ liệu —</p>
  }

  return (
    <div className={cn("text-sm leading-relaxed space-y-3", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 className="text-xl font-bold mt-4 mb-2">{children}</h1>,
          h2: ({ children }) => <h2 className="text-lg font-semibold mt-4 mb-2 pb-1 border-b">{children}</h2>,
          h3: ({ children }) => <h3 className="text-base font-semibold mt-3 mb-1.5">{children}</h3>,
          h4: ({ children }) => <h4 className="text-sm font-semibold mt-2.5 mb-1 text-foreground/90">{children}</h4>,
          h5: ({ children }) => <h5 className="text-sm font-medium mt-2 mb-1 text-foreground/80">{children}</h5>,
          p: ({ children }) => <p className="leading-relaxed">{children}</p>,
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer"
               className="text-[color:var(--chart-2)] underline underline-offset-2 hover:text-[color:var(--chart-2)]/80">
              {children}
            </a>
          ),
          strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
          em: ({ children }) => <em className="italic text-foreground/90">{children}</em>,
          code: ({ children, className }) => {
            // Block code (className present) vs inline code.
            if (className) {
              return (
                <pre className="rounded-md bg-muted/70 border p-3 my-2 overflow-x-auto text-xs">
                  <code className={className}>{children}</code>
                </pre>
              )
            }
            return <code className="rounded bg-muted px-1.5 py-0.5 text-[0.85em] font-mono">{children}</code>
          },
          ul: ({ children }) => <ul className="list-disc list-outside pl-5 space-y-1 my-2">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal list-outside pl-5 space-y-1 my-2">{children}</ol>,
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 pl-3 italic text-muted-foreground my-2">{children}</blockquote>
          ),
          hr: () => <hr className="my-4 border-border" />,
          table: ({ children }) => (
            <div className="my-3 overflow-x-auto rounded-md border">
              <table className="w-full text-xs tabular border-collapse">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-muted/60">{children}</thead>,
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => <tr className="border-b last:border-b-0">{children}</tr>,
          th: ({ children }) => <th className="px-3 py-2 text-left font-medium text-foreground/80">{children}</th>,
          td: ({ children }) => <td className="px-3 py-2 align-top">{children}</td>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
