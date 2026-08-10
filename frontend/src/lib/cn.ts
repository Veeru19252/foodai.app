/**
 * cn() — tiny class-name joiner (shadcn/ui uses clsx + tailwind-merge;
 * this dependency-free version covers the same usage for this demo).
 *
 *   cn("base", cond && "extra", { active: isActive }, ["array", "of", "classes"])
 */
export function cn(
  ...values: Array<string | false | null | undefined | Record<string, boolean> | string[]>
): string {
  const parts: string[] = [];
  for (const value of values) {
    if (!value) continue;
    if (typeof value === "string") {
      parts.push(value);
    } else if (Array.isArray(value)) {
      parts.push(...value.filter(Boolean));
    } else {
      for (const [key, enabled] of Object.entries(value)) {
        if (enabled) parts.push(key);
      }
    }
  }
  return parts.join(" ");
}
