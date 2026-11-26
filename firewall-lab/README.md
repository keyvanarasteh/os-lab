# firewall-lab: design your dream company's firewalls

A contribution lab for **BGT207 Güvenlik Duvarı Çözümleri**. Unlike the VM labs
([`linux-lab`](../linux-lab/), [`win-lab`](../win-lab/), …), nothing boots here.
This lab is a **growing book of network designs**: each student imagines a
company, works out its network and firewalls, and submits it as a pull request.
The dashboard renders every submission at **/firewall/**.

> The brief, from class: *imagine a company — offices in Ankara, İstanbul and
> London plus an academic campus of ~10,000 students. Give each branch its head
> counts, its bandwidth, its segmentation, the best five firewall products for
> each part (with price), a rule set you can explain line by line, a remote-access
> plan, and a monitoring plan that names who is responsible.*

## What's here

```
firewall-lab/
  README.md                 ← you are here
  schema/
    company.schema.json      the manifest contract (JSON Schema draft-07)
    README.md                field-by-field reference
  templates/company/         copy this to start your submission
  companies/                 ← every student's company lives here (PR target)
    acme-academy/            seed: multi-branch + 10k-student campus
    northwind-retail/        seed: small retailer, PCI segmentation
  knowledge/                 the concepts, grounded in what we covered
    segmentation.md  rule-ordering.md  product-selection.md  monitoring.md
  vm/                        a disposable guest to prototype a rule set and watch
                             it behave — renders to UFW, nftables, or a neutral
                             policy table (UFW is just the on-ramp)
  catalog.json / catalog.md  AUTO: every submitted firewall + its props, rebuilt on each PR
  scripts/
    validate.py              check a company against the schema (stdlib only)
    build-seed.py            compile companies → dashboard seed
    catalog.py               collect every firewall + props into catalog.{json,md}
```

## Find a firewall

The dashboard lists every deployed firewall at **/firewall/devices/** with search,
filters (vendor, segment, branch role, throughput, price) and a page per firewall.

## Ask an AI agent (MCP)

`console/mcp_firewall_server.py` is a read-only stdio MCP server with only the
Firewall Lab tools; the full `console/mcp_server.py` serves the same ones. Replace
`<REPO>` with the checkout path:

```json
{
  "mcpServers": {
    "os-lab-firewall": {
      "command": "python3",
      "args": ["<REPO>/console/mcp_firewall_server.py"]
    }
  }
}
```

Then ask, for example: *"A 1 Gbps branch office, about 200 people, under $10,000,
high availability. Which firewall?"* The agent can search (`firewall_devices`,
`firewall_products`), open and compare (`firewall_device`, `firewall_compare`) and
rank for the context (`firewall_recommend`). Throughput and prices are quoted by
students, not taken from vendor datasheets; confirm with the vendor before buying.

## Contribute your company (the exercise)

1. **Copy the template** into a new folder named with your company slug:
   ```sh
   cp -r firewall-lab/templates/company firewall-lab/companies/<your-slug>
   ```
   The folder name and the `slug` field must match (lowercase-kebab-case).
2. **Fill in `company.json`.** Every placeholder gets a real value. Read the
   [schema reference](schema/README.md) and the [knowledge](knowledge/) notes.
3. **Write `README.md`** next to it — the narrative the firewall JSON can't hold:
   your bandwidth reasoning, the product comparison in prose, the "why we did
   *not* choose" notes, your monitoring plan. This is the part the course grows
   "like a book."
4. **Validate, rebuild the seed, and refresh the catalog:**
   ```sh
   python3 firewall-lab/scripts/validate.py <your-slug>
   python3 firewall-lab/scripts/build-seed.py
   python3 firewall-lab/scripts/catalog.py
   ```
5. **(Optional) prototype it** in [`vm/`](vm/) — render your rules to UFW,
   nftables or a vendor-neutral table and apply them in a throwaway Ubuntu guest.
6. **Open a PR.** CI validates every company and republishes the firewall
   catalog on each PR. See [`companies/README.md`](companies/README.md) for the
   checklist and what reviewers look for.

## The rules of a good submission

Straight from the lecture notes:

- **Explain every rule.** A rule you cannot justify in one sentence is a
  vulnerability — the schema makes the `note` field mandatory for this reason.
- **Keep base services open:** DHCP (67/68), DNS (53), NTP (123). "Deny
  everything" takes the network down with it.
- **Segment by role** (staff / students / R&D / software / servers / management)
  and expose the public only through a **DMZ**.
- **Size subnets by devices, not people** — the campus needs far more than
  10,000 addresses.
- **No public SSH.** Admin access is a **role-based VPN** into a bastion.
- **Compare products with evidence** — throughput *with UTM on*, and price.
- **Name who owns monitoring.** An alert nobody owns is an alert nobody answers.
- Tracking a **current CVE** and your response (mitigation vs. patch) is bonus —
  and remember a normal firewall can't stop an application-layer bug.

## Not just UFW

We started with [UFW](https://help.ubuntu.com/community/UFW) to learn the three
things **every** firewall shares — rules, their **order**, and the **default
policy** — not because the answer is always UFW. Those ideas are identical on
pfSense, OPNsense and FortiGate, which is why a company's rules are written once,
abstractly, and [`vm/`](vm/) renders them to UFW, nftables (the filter
pfSense/OPNsense generate underneath) **or** a vendor-neutral policy table you
translate onto any appliance. Prototype in the throwaway guest, and wire block
alerts to Telegram with [`ufw-logger`](https://github.com/keyvanarasteh/ufw-logger).
This lab is a candidate midterm capability in the os-lab pipeline.

## Contributors

Students who contributed company designs are listed (names masked) in [CONTRIBUTORS.md](CONTRIBUTORS.md).
