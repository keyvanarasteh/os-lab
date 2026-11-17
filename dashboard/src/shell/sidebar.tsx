/**
 * App sidebar, ported from the iQ-iUX studio (src/components/app-sidebar.tsx) with its look and behaviour:
 *
 * - Expanded: a Quick search field (⌘K) that opens Spotlight, group labels, items with chevrons,
 *   nested levels on a guide line, pill badges.
 * - Collapsed icon rail: tooltips, and a click EXPANDS the sidebar (opening the item's submenu)
 *   instead of navigating, so nothing opens by accident.
 * - The toggle at the top collapses/expands, and a click outside the expanded sidebar collapses it; the choice is
 *   remembered per `storageKey`.
 * - `variant="drawer"` renders the expanded sidebar without the collapse controls, for the mobile drawer.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode
} from "react";
import {
  CaretDownIcon,
  CaretRightIcon,
  MagnifyingGlassIcon,
  SidebarSimpleIcon
} from "@phosphor-icons/react";

export interface SidebarLeaf {
  id: string;
  label: string;
  badge?: ReactNode;
  /** Optional small glyph before the label. */
  icon?: ReactNode;
  /** Only for admin accounts; hidden from everyone else's sidebar and Spotlight. */
  admin?: boolean;
}

export interface SidebarItem {
  id: string;
  label: string;
  icon: ReactNode;
  badge?: ReactNode;
  /** Only for admin accounts; hidden from everyone else's sidebar and Spotlight. */
  admin?: boolean;
  /** Nested level; the item then toggles open instead of navigating. */
  children?: SidebarLeaf[];
}

export interface SidebarGroup {
  label: string;
  items: SidebarItem[];
  /** The label becomes a button that folds the group's items away. */
  collapsible?: boolean;
  /** For a collapsible group: open until the user folds it. Default false (closed). */
  defaultOpen?: boolean;
}

export function cn(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

/** Small pill, e.g. "New" or a count. */
export function SidebarBadge({
  children,
  tone = "accent"
}: {
  children: ReactNode;
  tone?: "accent" | "warn";
}) {
  return (
    <span
      className={cn(
        "ml-auto rounded-full border px-1.5 py-px text-[10px] leading-none font-medium",
        tone === "warn"
          ? "border-(--iux-warning)/30 bg-(--iux-warning)/10 text-(--iux-warning)"
          : "border-(--iux-primary)/30 bg-(--iux-primary)/10 text-(--iux-primary)"
      )}
    >
      {children}
    </span>
  );
}

/** Collapsed state, remembered in localStorage (which can be unavailable: private mode, blocked storage). */
export function useSidebarCollapsed(
  storageKey: string
): [boolean, (collapsed: boolean) => void] {
  // The pages render only in the browser, so storage can be read up front
  const [collapsed, setCollapsedState] = useState(() => {
    try {
      return window.localStorage.getItem(storageKey) === "1";
    } catch {
      return false;
    }
  });

  const setCollapsed = useCallback(
    (next: boolean) => {
      setCollapsedState(next);
      try {
        window.localStorage.setItem(storageKey, next ? "1" : "0");
      } catch {
        // Storage unavailable: the choice lasts for this page view
      }
    },
    [storageKey]
  );
  return [collapsed, setCollapsed];
}

const GROUPS_KEY = "oslab.sidebar.groups";

function readGroupState(): Record<string, boolean> {
  try {
    const raw = window.localStorage.getItem(GROUPS_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : null;
    return parsed && typeof parsed === "object" ? (parsed as Record<string, boolean>) : {};
  } catch {
    return {};
  }
}

function writeGroupState(state: Record<string, boolean>) {
  try {
    window.localStorage.setItem(GROUPS_KEY, JSON.stringify(state));
  } catch {
    // Storage unavailable: the choice lasts for this page view
  }
}

interface AppSidebarProps {
  groups: SidebarGroup[];
  activeId: string;
  onSelect: (id: string) => void;
  /** `toggle` is the collapse button for the expanded header to place; the rail shows it under the header itself. */
  header: (collapsed: boolean, toggle: ReactNode) => ReactNode;
  footer?: (collapsed: boolean) => ReactNode;
  variant?: "desktop" | "drawer";
  collapsed?: boolean;
  onCollapsedChange?: (collapsed: boolean) => void;
  searchPlaceholder?: string;
  /** Opens Spotlight; the search field and the rail's search icon become triggers for it. */
  onSearch?: () => void;
}

const rowBase =
  "flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-left text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-(--iux-ring)";
const rowIdle =
  "text-(--iux-muted-foreground) hover:bg-(--iux-accent)/60 hover:text-(--iux-foreground)";
const rowActive = "bg-(--iux-accent) text-(--iux-foreground)";

export function AppSidebar({
  groups,
  activeId,
  onSelect,
  header,
  footer,
  variant = "desktop",
  collapsed: collapsedProp = false,
  onCollapsedChange,
  searchPlaceholder = "Quick search…",
  onSearch
}: AppSidebarProps) {
  const isDrawer = variant === "drawer";
  const collapsed = !isDrawer && collapsedProp;
  // Explicit open/closed choices; an item without one is open exactly when it holds the active page
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  // Collapsible groups (Help): the user's choice is remembered; a group holding the active page opens itself.
  const [groupToggled, setGroupToggled] = useState<Record<string, boolean>>(readGroupState);

  const parentOf = useMemo(() => {
    const map = new Map<string, string>();
    for (const g of groups)
      for (const item of g.items)
        for (const leaf of item.children ?? []) map.set(leaf.id, item.id);
    return map;
  }, [groups]);

  const groupHoldsActive = (group: SidebarGroup) =>
    group.items.some((item) => item.id === activeId || (item.children ?? []).some((leaf) => leaf.id === activeId));
  const isGroupOpen = (group: SidebarGroup) =>
    !group.collapsible || (groupToggled[group.label] ?? (group.defaultOpen ?? false));
  const toggleGroup = (group: SidebarGroup) =>
    setGroupToggled((prev) => {
      const next = { ...prev, [group.label]: !isGroupOpen(group) };
      writeGroupState(next);
      return next;
    });
  // Landing on a page inside a folded group opens it (without overriding what is stored for later visits).
  useEffect(() => {
    for (const group of groups) {
      if (group.collapsible && groupHoldsActive(group) && !isGroupOpen(group))
        setGroupToggled((prev) => ({ ...prev, [group.label]: true }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, groups]);

  const isOpenItem = (id: string) =>
    toggled[id] ?? parentOf.get(activeId) === id;

  const expand = useCallback(
    (openItem?: string) => {
      onCollapsedChange?.(false);
      if (openItem) setToggled((prev) => ({ ...prev, [openItem]: true }));
    },
    [onCollapsedChange]
  );

  // A click outside the expanded sidebar collapses it, except inside an open dialog such as Spotlight
  const asideRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (isDrawer || collapsed || !onCollapsedChange) return;
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Element | null;
      if (!target || asideRef.current?.contains(target)) return;
      if (target.closest("dialog[open]")) return;
      onCollapsedChange(true);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [isDrawer, collapsed, onCollapsedChange]);

  const toggle = isDrawer ? null : (
    <RailButton
      label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      icon={<SidebarSimpleIcon size={16} />}
      onClick={() => onCollapsedChange?.(!collapsed)}
      pressed={collapsed}
    />
  );

  const body = (
    <>
      {header(collapsed, collapsed ? null : toggle)}
      {collapsed && (
        <div className="flex justify-center px-2 pt-2">{toggle}</div>
      )}

      <div className={cn("px-2 pt-2", collapsed && "flex justify-center")}>
        {collapsed ? (
          <RailButton
            label="Search (⌘K)"
            icon={<MagnifyingGlassIcon size={16} />}
            onClick={() => onSearch?.()}
          />
        ) : (
          <button
            type="button"
            onClick={() => onSearch?.()}
            aria-label="Open search"
            className="flex h-9 w-full items-center gap-2 rounded-md border border-(--iux-input) bg-(--iux-background)/60 px-2.5 text-sm text-(--iux-muted-foreground) outline-none transition-colors hover:bg-(--iux-accent)/60 focus-visible:ring-2 focus-visible:ring-(--iux-ring)"
          >
            <MagnifyingGlassIcon size={16} className="shrink-0" />
            <span className="truncate">{searchPlaceholder}</span>
            {!isDrawer && (
              <kbd className="ml-auto rounded border border-(--iux-border) px-1 text-[10px]">
                ⌘K
              </kbd>
            )}
          </button>
        )}
      </div>

      <nav
        className="iux-scroll flex flex-1 flex-col gap-0.5 overflow-y-auto p-2"
        aria-label="Sections"
      >
        {groups.map((group, gi) => (
          <div
            key={group.label}
            className={cn(
              "flex flex-col gap-0.5",
              collapsed ? "items-stretch" : "pb-2"
            )}
          >
            {collapsed ? (
              gi > 0 ? (
                <hr className="mx-2 my-2 border-(--iux-border)" />
              ) : null
            ) : group.collapsible ? (
              <button
                type="button"
                aria-expanded={isGroupOpen(group)}
                aria-controls={`sidebar-group-${gi}`}
                onClick={() => toggleGroup(group)}
                className="flex w-full items-center gap-1 rounded-md px-3 pt-3 pb-1 text-left text-xs font-medium text-(--iux-muted-foreground)/70 outline-none transition-colors hover:text-(--iux-foreground) focus-visible:ring-2 focus-visible:ring-(--iux-ring)"
              >
                <span>{group.label}</span>
                {isGroupOpen(group) ? (
                  <CaretDownIcon size={12} className="ml-auto shrink-0" />
                ) : (
                  <CaretRightIcon size={12} className="ml-auto shrink-0" />
                )}
              </button>
            ) : (
              <div className="px-3 pt-3 pb-1 text-xs font-medium text-(--iux-muted-foreground)/70">
                {group.label}
              </div>
            )}
            <div
              id={`sidebar-group-${gi}`}
              className="flex flex-col gap-0.5"
              hidden={!collapsed && !isGroupOpen(group)}
            >
            {group.items.map((item) => {
              const kids = item.children ?? [];
              const childActive = kids.some((c) => c.id === activeId);
              const isOpen = isOpenItem(item.id);
              const active = item.id === activeId || (childActive && !isOpen);

              if (collapsed) {
                // A click expands the sidebar (and this item's submenu); it never opens a page
                return (
                  <RailButton
                    key={item.id}
                    label={item.label}
                    icon={item.icon}
                    onClick={() =>
                      expand(kids.length > 0 ? item.id : undefined)
                    }
                    active={active || childActive}
                  />
                );
              }

              if (kids.length === 0) {
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => onSelect(item.id)}
                    aria-current={item.id === activeId ? "page" : undefined}
                    className={cn(
                      rowBase,
                      item.id === activeId ? rowActive : rowIdle
                    )}
                  >
                    {item.icon}
                    <span className="truncate">{item.label}</span>
                    {item.badge}
                  </button>
                );
              }

              const Caret = isOpen ? CaretDownIcon : CaretRightIcon;
              return (
                <div key={item.id} className="flex flex-col">
                  <button
                    type="button"
                    aria-expanded={isOpen}
                    onClick={() =>
                      setToggled((prev) => ({ ...prev, [item.id]: !isOpen }))
                    }
                    className={cn(rowBase, active ? rowActive : rowIdle)}
                  >
                    {item.icon}
                    <span className="truncate">{item.label}</span>
                    {item.badge}
                    <Caret
                      size={14}
                      className={cn("shrink-0", !item.badge && "ml-auto")}
                    />
                  </button>
                  {isOpen && (
                    <ul className="mt-0.5 mb-1 ml-[19px] flex flex-col gap-0.5 border-l border-(--iux-border) pl-2">
                      {kids.map((leaf) => (
                        <li key={leaf.id}>
                          <button
                            type="button"
                            onClick={() => onSelect(leaf.id)}
                            aria-current={
                              leaf.id === activeId ? "page" : undefined
                            }
                            className={cn(
                              "flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-(--iux-ring)",
                              leaf.id === activeId
                                ? `${rowActive} font-medium`
                                : rowIdle
                            )}
                          >
                            {leaf.icon && <span className="shrink-0">{leaf.icon}</span>}
                            <span className="truncate">{leaf.label}</span>
                            {leaf.badge}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}
            </div>
          </div>
        ))}
      </nav>

      {footer && !collapsed ? footer(collapsed) : null}
    </>
  );

  if (isDrawer)
    return <div className="flex min-h-0 flex-1 flex-col">{body}</div>;
  return (
    <aside
      ref={asideRef}
      className={cn(
        "iux sticky top-0 hidden h-full shrink-0 flex-col border-r border-(--iux-border) bg-(--iux-sidebar) pb-[env(safe-area-inset-bottom)] transition-[width] duration-200 lg:flex",
        collapsed ? "w-14" : "w-60"
      )}
    >
      {body}
    </aside>
  );
}

/** Icon button with a tooltip to its right (the rail, the search icon, the collapse toggle). */
function RailButton({
  label,
  icon,
  onClick,
  active = false,
  pressed
}: {
  label: string;
  icon: ReactNode;
  onClick: () => void;
  active?: boolean;
  pressed?: boolean;
}) {
  // Fixed position, so the scrolling nav doesn't clip the tooltip
  const [tip, setTip] = useState<{ top: number; left: number } | null>(null);
  const show = (e: { currentTarget: HTMLElement }) => {
    const rect = e.currentTarget.getBoundingClientRect();
    setTip({ top: rect.top + rect.height / 2, left: rect.right + 8 });
  };
  const hide = () => setTip(null);

  return (
    <>
      <button
        type="button"
        onClick={() => {
          hide();
          onClick();
        }}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        aria-label={label}
        aria-current={active ? "page" : undefined}
        aria-pressed={pressed}
        className={cn(
          "mx-auto flex size-9 items-center justify-center rounded-md outline-none transition-colors focus-visible:ring-2 focus-visible:ring-(--iux-ring)",
          active ? rowActive : rowIdle
        )}
      >
        {icon}
      </button>
      {tip && (
        <span
          role="tooltip"
          style={{ top: tip.top, left: tip.left }}
          className="pointer-events-none fixed z-50 -translate-y-1/2 rounded-md bg-(--iux-primary) px-2 py-1 text-xs whitespace-nowrap text-(--iux-primary-foreground)"
        >
          {label}
        </span>
      )}
    </>
  );
}
