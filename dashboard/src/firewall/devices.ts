/**
 * Every deployed firewall of every company as one flat list, for /firewall/devices/ and /firewall/device/.
 *
 * console/firewall_catalog.py builds the same list for the MCP tools. Ids, vendors and categories must
 * agree; both read firewall-lab/normalize.json and scripts/firewall-devices.test.mjs compares them.
 */
import rules from "../../../firewall-lab/normalize.json";
import type { Branch, BranchRole, Company, Firewall, Product } from "./types";

export type FirewallCategory = "firewall" | "waf";

export interface ProductInfo {
  vendor: string;
  model: string;
  category: FirewallCategory;
  ha: boolean;
  openSource: boolean;
  productKey: string;
}

export interface FirewallDevice extends ProductInfo {
  id: string;
  company: Company;
  branch: Branch;
  firewall: Firewall;
}

export const slug = (text: string) => String(text).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "x";

const aliases: Record<string, string> = rules.vendorAliases;

export function classify(quoted: Pick<Product, "vendor" | "product">): ProductInfo {
  const vendor = String(quoted.vendor).trim();
  const raw = String(quoted.product).trim();
  const canonical = aliases[vendor] ?? vendor;
  let model = raw;
  for (const pattern of rules.modelNoisePatterns) model = model.replace(new RegExp(pattern, "g"), "");
  for (let stripped = true; stripped;) {
    stripped = false;
    for (const prefix of rules.modelPrefixes) {
      if (model.toLowerCase().startsWith(`${prefix.toLowerCase()} `)) {
        model = model.slice(prefix.length + 1);
        stripped = true;
      }
    }
  }
  model = model.replace(/\s+/g, " ").trim() || raw;
  const waf = new RegExp(rules.wafPattern, "i").test(raw) && !new RegExp(rules.networkFirewallPattern, "i").test(raw);
  return {
    vendor: canonical,
    model,
    category: waf ? "waf" : "firewall",
    ha: new RegExp(rules.haPattern).test(raw),
    openSource: new RegExp(rules.openSourcePattern, "i").test(`${vendor} ${raw}`),
    productKey: slug(`${canonical} ${model}`)
  };
}

export function listDevices(companies: Company[]): FirewallDevice[] {
  const seen = new Map<string, number>();
  return companies.flatMap((company) => (company.branches ?? []).flatMap((branch) => (branch.firewalls ?? []).map((firewall) => {
    const base = `${company.slug}--${branch.id}--${slug(firewall.segment)}`;
    const count = (seen.get(base) ?? 0) + 1;
    seen.set(base, count);
    return { ...classify(firewall.chosen), id: count === 1 ? base : `${base}-${count}`, company, branch, firewall };
  })));
}

export const SORTS = ["company", "vendor", "product", "price-asc", "price-desc", "throughput-desc", "throughput-asc"] as const;
export type DeviceSort = typeof SORTS[number];

/** Every field is the raw text of its control, so the filters round-trip through the address bar. */
export interface DeviceFilters {
  q: string;
  vendor: string;
  segment: string;
  role: BranchRole | "";
  category: FirewallCategory | "";
  company: string;
  minGbps: string;
  maxPrice: string;
  openSource: "1" | "";
  alternatives: "1" | "";
  sort: DeviceSort;
}

export const NO_FILTERS: DeviceFilters = {
  q: "", vendor: "", segment: "", role: "", category: "", company: "", minGbps: "", maxPrice: "",
  openSource: "", alternatives: "", sort: "company"
};
const KEYS = Object.keys(NO_FILTERS) as (keyof DeviceFilters)[];

export function readFilters(search: string): DeviceFilters {
  const params = new URLSearchParams(search);
  const filters = { ...NO_FILTERS } as Record<keyof DeviceFilters, string>;
  for (const key of KEYS) filters[key] = params.get(key) ?? NO_FILTERS[key];
  if (!(SORTS as readonly string[]).includes(filters.sort)) filters.sort = NO_FILTERS.sort;
  return filters as DeviceFilters;
}

/** The filters that differ from the defaults, as a query string without "?". */
export function writeFilters(filters: DeviceFilters): string {
  const params = new URLSearchParams();
  for (const key of KEYS) if (filters[key] !== NO_FILTERS[key]) params.set(key, filters[key]);
  return params.toString();
}

const limit = (text: string) => (text.trim() === "" || !Number.isFinite(Number(text)) ? null : Number(text));
const words = (query: string) => query.toLowerCase().split(/\s+/).filter(Boolean);
const matches = (text: string, query: string[]) => { const hay = text.toLowerCase(); return query.every((word) => hay.includes(word)); };

function ownText({ company, branch, firewall, vendor, model }: FirewallDevice): string {
  return [firewall.chosen.product, model, vendor, firewall.chosen.vendor, company.name, company.sector, branch.name,
    branch.location, firewall.segment, branch.role, firewall.chosen.reason].filter(Boolean).join(" ");
}

/** The compared alternative that made a device match, when its own fields do not. */
export function matchedAlternative(device: FirewallDevice, filters: DeviceFilters): Product | undefined {
  const query = words(filters.q);
  if (!filters.alternatives || !query.length || matches(ownText(device), query)) return undefined;
  return device.firewall.alternatives.find((item) => matches(`${ownText(device)} ${item.vendor} ${item.product}`, query));
}

export function filterDevices(devices: FirewallDevice[], filters: DeviceFilters): FirewallDevice[] {
  const query = words(filters.q);
  const minGbps = limit(filters.minGbps);
  const maxPrice = limit(filters.maxPrice);
  const found = devices.filter((device) => {
    const { chosen, segment } = device.firewall;
    if (filters.vendor && device.vendor !== filters.vendor) return false;
    if (filters.segment && segment !== filters.segment) return false;
    if (filters.role && device.branch.role !== filters.role) return false;
    if (filters.category && device.category !== filters.category) return false;
    if (filters.company && device.company.slug !== filters.company) return false;
    if (filters.openSource && !device.openSource) return false;
    if (minGbps !== null && (chosen.throughputGbps == null || chosen.throughputGbps < minGbps)) return false;
    if (maxPrice !== null && (chosen.priceUsd == null || chosen.priceUsd > maxPrice)) return false;
    if (!query.length) return true;
    const own = ownText(device);
    if (matches(own, query)) return true;
    return Boolean(filters.alternatives) && matches(`${own} ${device.firewall.alternatives.map((a) => `${a.vendor} ${a.product}`).join(" ")}`, query);
  });
  return sortDevices(found, filters.sort);
}

/** Sort a copy; a device without the sorted number goes last in either direction. */
export function sortDevices(devices: FirewallDevice[], sort: DeviceSort): FirewallDevice[] {
  const text = (value: (device: FirewallDevice) => string) => [...devices].sort((a, b) => value(a).localeCompare(value(b)));
  if (sort === "company") return text((device) => device.company.name);
  if (sort === "vendor") return text((device) => `${device.vendor} ${device.model}`);
  if (sort === "product") return text((device) => device.model);
  const [field, direction] = sort.split("-");
  const value = (device: FirewallDevice) => (field === "price" ? device.firewall.chosen.priceUsd : device.firewall.chosen.throughputGbps);
  return [...devices].sort((a, b) => {
    const left = value(a), right = value(b);
    if (left == null || right == null) return Number(left == null) - Number(right == null);
    return direction === "asc" ? left - right : right - left;
  });
}
