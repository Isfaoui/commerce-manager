# Commerce Manager

A restaurant/retail management system: dashboard, POS (caisse), inventory
& purchasing, staff, and settings - one desktop app.

## Project structure

```
CommerceManager/
├── main.py              entry point - starts the server + opens the app window
├── controllers/
│   └── app.py             all API routes (Flask)
├── models/
│   └── db.py               database connection, paths, schema creation
├── utils/
│   └── helpers.py           hashing, timestamps, approval verification
├── views/                 the interface (HTML/CSS/JS) - dashboard, caisse,
│                            management, staff, settings pages
├── database/
│   ├── seed.py              creates roles, employees, tables, products
│   └── schema.sql           human-readable schema reference
├── assets/                 put your app icon here (icon.ico)
├── exports/                 reserved for future report exports (CSV/PDF)
├── backups/                 reserved for future database backups
├── requirements.txt
├── install.bat / run.bat     Windows: install once, run every time
├── run.sh                    Mac/Linux equivalent
├── CommerceManager.spec      PyInstaller build config -> real .exe
├── CommerceManager.iss       Inno Setup config -> real Windows installer
└── BUILD.md                  how to build the .exe and the installer
```

## Quick start

**One-time setup:** install Python from https://www.python.org/downloads/
— tick **"Add Python to PATH"** during install.

**Windows:**
1. Double-click `install.bat` (once)
2. Double-click `run.bat` (every time after that)

**Mac/Linux:**
```
chmod +x run.sh
./run.sh
```

A real app window opens - no browser tabs, no address bar. On Windows,
no console window either.

**Want an actual installed program** (Setup wizard, Start Menu entry,
Desktop icon, proper uninstaller)? See `BUILD.md` - two commands, run
once on your machine.

## Editing and deleting

- **Products**: in Gestion → Inventaire, each row has **Modifier** (loads
  it into the form above, type locked since simple/recipe can't change
  after creation) and **Supprimer**. Deleting is a soft delete - it
  disappears from the caisse and inventory list, but past sales that
  included it keep their historical record intact. A raw material still
  used in an active recipe can't be deleted until you remove it from
  that recipe first.
- **Purchase orders**: in Gestion → Achats, **Supprimer** reverses the
  stock it added (and the supplier balance, if any). It does *not*
  revert the product's cost_price, since that may have been overwritten
  by a later purchase since - the confirmation dialog says so.

## Receipts

**Parametres → Ticket de caisse** controls receipts:
- A toggle to turn receipts off entirely - when off, nothing pops up
  automatically after a payment in the caisse. Sales are still recorded
  and reachable in Gestion → Ventes for manual reprint any time -
  disabling just turns off the automatic prompt, it doesn't erase
  history.
- Custom address, phone, and thank-you message shown on every receipt,
  with a live preview right there so you can see exactly what it'll
  look like before saving.

Gestion → **Ventes** lists every sale with an **Imprimer** button to
reprint any past receipt - that's the permanent home for receipts, not
just the moment right after a sale.

In the caisse, a receipt now opens as an **in-page panel** right after
payment (not a separate popup window) - popups are unreliable inside a
desktop app shell like this one and can get silently blocked, so this
is the more robust approach. Click **Imprimer** in that panel to print
it.

## Product photos

Add a photo when creating or editing a product in Gestion → Inventaire
(PNG/JPG/WEBP/GIF, 5MB max). Shows as a thumbnail in the inventory list
and as the tile image in the caisse; products without a photo show a
neutral placeholder instead.

Photos are saved in an `uploads/products/` folder next to the database -
**not** inside the bundled app files, since those get wiped on every
restart once packaged as a `.exe`. This folder needs to travel with your
database if you ever move the installation.

## Tax on sales (TTC)

Your sale prices are treated as **TTC** (tax already included - what the
customer actually pays never changes). The rate set in Parametres is
used to extract the tax portion for display: Sous-total (HT) + TVA =
Total (TTC), shown on the cart, the receipt, and in Rapports as "TVA
collectee". Nothing is added on top of your prices - this is purely a
breakdown of what's already in them, which is what Moroccan retail
pricing law expects.

The rate is snapshotted onto each sale at the moment it's made, so
changing it later doesn't alter historical reports. Reports
(chiffre d'affaires, marge) use the HT amount as revenue, since the tax
portion isn't real business income - it's collected on behalf of the
state.

## Kitchen / fulfillment tracking ("Servi")

Every order (Sur place, A emporter, or Livraison) tracks a separate
"Servi" status alongside its payment status - the two are independent,
since takeaway/delivery are often paid before prep while dine-in is
often paid after. The caisse's **Commandes en cours** panel shows both:
an order stays visible until it's *both* paid and served, with a
**Marquer comme servi** button for the ones still pending.

## Apparence (V2)

**Parametres → Apparence**: light/dark/auto mode, and one custom brand
color (with a few presets or the native color picker for any hex).
Applies instantly on save, no restart - every page fetches the current
theme on load, so it's consistent across Accueil/Caisse/Gestion/
Personnel/Parametres.

Deliberately scoped to one color, not nine separate tokens (primary/
secondary/sidebar/success/etc as some POS systems offer) - a single
brand color plus a dark-mode-appropriate derived palette covers what
actually matters. The engine lives in one shared file, `views/theme.js`,
loaded by every page - the first genuinely shared script in the
codebase (everything else duplicates small blocks per page, which was
the right tradeoff for small pieces, but not for something every page
needs identically).

Printed receipts are intentionally NOT themed - they stay high-contrast
regardless of your screen's dark mode, since paper doesn't have a dark
mode.

## Graphiques sur le tableau de bord (V2)

Accueil now shows a 7-day revenue trend and a best-sellers bar chart,
built as plain HTML/CSS bars rather than a charting library - this app
is meant to work fully offline on one machine, and a CDN-hosted charting
library would work against that the moment there's no internet.

## Clients / CRM + credit balance ("ardoise") (V2)

A new **Clients** section: name/phone/email/address, a running credit
balance, order history, and a way to record payments against that
balance. This is what finally makes "Crédit client" actually work - it
existed as a payment method label since V1 with nothing behind it.

How it works: payment methods can be flagged "Credit client" in
Parametres. Using one of those in the caisse requires a customer to be
selected first (enforced server-side, not just in the UI) - the sale
completes normally (goods delivered), but the amount is added to that
customer's balance instead of being counted as cash collected. Pay
down a balance any time from **Clients** → **Gerer** → a customer.
Deleting a customer is blocked while they have a nonzero balance.

## Sauvegarde et restauration locale (V2)

**Parametres → Sauvegarde et restauration**: a real backup system, not
just a folder placeholder. Each backup is a single ZIP file containing
the full database *and* every product photo - restoring one brings
back everything together, not just the numbers with broken image links.

- One automatic backup per calendar day (restarting the app repeatedly
  doesn't pile up duplicates); the last 5 are kept automatically.
- **Creer une sauvegarde maintenant** for a manual one anytime.
- **Telecharger** to save a copy outside this computer (a USB drive, a
  cloud-synced folder) - genuinely important, since a local-only backup
  doesn't protect against the computer itself failing.
- **Restaurer** replaces all current data with that snapshot - tested by
  actually deleting a product, restoring, and confirming it came back.
  This is destructive and irreversible by design (it's an undo of
  everything since that snapshot), so it asks for confirmation and tells
  you to restart the app afterward.

## Remises et mise en attente (V2)

**Remise** - in the caisse, a discount field above the total (percentage
or fixed MAD amount). Applied to the pre-tax total, then tax is
recalculated on the discounted amount - so a 10% discount on a 120 MAD
(TTC) sale means the customer pays 108 MAD total, not 120 minus a
discount added as an afterthought. A fixed discount can never exceed
the sale total (no negative totals). Splitting a discounted order keeps
the discount correctly distributed across the split tickets.

**Mettre en attente** - saves the current cart without creating a real
order or touching stock, for when a cashier gets interrupted mid-sale.
Held orders show in a small panel and can be recalled (restoring the
cart, discount, and table) or discarded. This is stored locally on this
device (not synced anywhere), and only applies to carts not yet sent -
once "Envoyer la commande" is clicked, it's a real order like any other.

## Modeles de recu et export (V2)

**Parametres → Ticket de caisse** now includes a template picker:
Classique, Moderne, Minimal - same information, different visual
styling, with the live preview reflecting whichever is selected.

**Gestion → Ventes**: "Exporter en CSV" downloads the full sales history.

**Gestion → Rapports**: "Exporter en CSV" downloads the summary, 7-day
trend, and best-sellers together in one file. "Imprimer / Exporter en
PDF" opens a print-friendly report and your browser's print dialog -
choosing "Save as PDF" there is how you get a PDF. This deliberately
doesn't pull in a PDF-generation library: the app is meant to work
fully offline, and every OS already has "print to PDF" built into its
print dialog, so this gets the same result without a new dependency.

## Centre de notifications

A "Notifications" button in the nav bar on every page, with an unread
count badge. Combines two kinds of signals:
- **Live conditions** - low-stock products, recomputed every time you
  open it (not stored as one-time events, since "still low" isn't a new
  event each time).
- **Logged events** - manual backups created, and every cancellation/
  refund (with who and how much) - these persist with a real timestamp
  and can be marked read.

"Tout marquer lu" clears the event badge; low-stock items stay visible
as long as the condition is true, since marking them "read" wouldn't
make the stock less low.

## Products: simple vs. recipe (this matters for a cafe/restaurant)

Not everything you sell works the same way:

- **Simple products** - you buy them and resell them as-is (water, soda,
  bottled drinks). They have a cost, a sale price, and their own stock.
- **Recipe products** - you make them from ingredients (a coffee = coffee
  beans + milk). You don't set a cost or stock for the coffee itself -
  you set it for the raw materials (in grams/ml), build a recipe, and the
  system computes the coffee's cost and how many you can still make from
  what's in stock, automatically.

In **Gestion -> Inventaire**, when adding a product, choose "Simple" or
"Recette". For raw materials that are never sold directly (coffee beans,
milk), also uncheck "Vendable directement" - they'll still track stock
and appear in purchasing, just not in the caisse.

Selling a recipe item consumes its ingredients' stock, not its own. If
you don't have enough milk, the sale is blocked with a clear message -
same as running out of a simple product. Cancelling/refunding a recipe
sale puts the ingredients back. Profit reports use the ingredient cost
at the time of the sale, so they stay accurate even if ingredient prices
change later.

## Caisse additions

- **Search bar** above the product grid - filters by name as you type.
- **"+ Article libre"** button - for one-off sales that don't deserve a
  permanent catalog entry (a tip, a custom service charge). No stock
  impact, no cost tracked.
- **Receipt printing** - after payment, a print-ready receipt opens
  automatically and calls your browser's print dialog. This works with
  any printer set up normally in Windows, including most receipt
  printers (they usually install as a standard printer driver). It does
  *not* do raw ESC/POS thermal printing - if your printer needs that
  specifically, that's a separate integration.

## First launch: business type

The first time the app runs, it asks you to pick a business type
(Restaurant, Cafe, Epicerie/Commerce de detail, Service, or Autre).
**This choice is permanent** - it's enforced both in the interface and
on the server (`POST /api/settings` rejects any attempt to change
`business_type` once it's set), so it can't be bypassed by editing the
page. Confirming it also seeds a set of starting categories suited to
that business type (e.g. "Entrees/Plats/Desserts/Boissons" for a
restaurant, "Boissons chaudes/froides, Patisseries, Snacks" for a cafe).

This choice drives the caisse:
- **Restaurant / Cafe / Autre** - all three order types (Sur place,
  A emporter, Livraison), tables enabled for dine-in
- **Epicerie / Service** - a single sale type, no order-type tabs or
  tables shown, since they don't apply

Confirming it also auto-creates the three default roles (Owner, Manager,
Cashier) - these are structural, not demo data, so they exist whether or
not you ever run `database/seed.py`. Without them the staff role dropdown
would be empty.

Recipes (products made from ingredients, in **Gestion → Inventaire**)
only show up for Restaurant/Cafe/Autre - hidden entirely for Epicerie
and Service, since neither typically manufactures what they sell.

**Tables** work the same way: they're not created automatically. Go to
**Gestion → Tables** (visible for Restaurant/Cafe/Autre) and add at
least one before "Sur place" will work in the caisse - the "Envoyer la
commande" button stays disabled until a table is selected, and without
any tables to select, that's why it looks stuck.

To change the mapping of business types to order types, edit
`BUSINESS_TYPE_CONFIG` near the top of the script in `views/index.html`.
To change the default categories per type, edit
`DEFAULT_CATEGORIES_BY_TYPE` in `controllers/app.py`. To change which
business types get the recipe option or the Tables tab, edit
`RECIPE_ENABLED_TYPES` / `TABLES_ENABLED_TYPES` near the top of the
script in `views/management.html`.

## Barcodes

- Add a barcode when creating a product in **Gestion → Inventaire**
  (optional field; duplicates are rejected with a clear error).
- In the **Caisse**, there's a barcode field in the header - scan or
  type a code and press Enter to add that product to the cart directly.
  A USB/Bluetooth barcode scanner works out of the box here: scanners
  just "type" the code followed by Enter, so no special driver or
  integration is needed.

## Test credentials

| Employee | Role | PIN | Password | NFC card ID |
|---|---|---|---|---|
| Ahmed | Owner | 1234 | owner123 | NFC-OWNER-01 |
| Sara | Manager | 5678 | manager123 | NFC-MGR-01 |
| Youssef | Cashier | 0000 | cashier123 | NFC-CASH-01 |

Only owner/manager can approve cancellations & refunds. Try it with
Youssef's PIN in the caisse (rejected), then Sara's (approved).

## The five modules

- **Accueil** - today's revenue, open orders, recent transactions,
  low-stock alerts, best sellers, who's clocked in.
- **Caisse** - dine-in/takeaway/delivery, table picking, split bills,
  cash/card/simulated-TPE payment, approval-gated cancel/refund.
- **Gestion** - inventory, suppliers, purchase orders (receiving stock
  updates quantity + cost live), reports (revenue/cost/profit, best
  sellers, sales by day).
- **Personnel** - employees, roles, clock in/out, attendance.
- **Parametres** - store info, payment methods, and the full security
  audit log of every cancellation/refund.

## What's simulated (needs real integration before production)

- **TPE (payment terminal)** - `controllers/app.py`'s `tpe_charge()` is
  a stub that always approves. Replace with your terminal vendor's SDK.
- **NFC card reading** - a text field stands in for a reader. Everything
  downstream already works off the card ID string.
- **PIN/password hashing** - sha256 for clarity; use bcrypt/argon2
  before handling real credentials.
- **No login/session system** - add real authentication before multiple
  people share a till unsupervised.

## Known simplifications

- Single tenant, single store.
- Split bills: UI does a 2-way split; the API (`POST /api/orders/<id>/split`)
  supports any number of groups.
- Purchase orders are always "received" immediately - no draft/ordered
  pipeline yet.
- Reports are numbers, no charts yet - `exports/` is reserved for CSV/PDF
  export, not built yet.
- Receipt printing uses the browser print dialog (works with any
  Windows-installed printer driver); raw ESC/POS thermal printing is a
  separate, more advanced integration if your printer needs it.
