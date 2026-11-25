# brieblue-listing-agent

A photo-to-listing **agent** for artisan textiles — built for Brieblue, an
importer of Asian artisan goods, for the Muse Ember Hackathon.

This is not an image analyzer. It is a listing agent: it does the first-draft
work a seller does for every new piece, end to end.

## What it does

1. **Photo in.** You give it one product photo of a textile.
2. **Ember drafts the listing.** Muse Ember looks at the photo and writes a
   structured, buyer-searchable listing: title, tradition, motifs, colors,
   tags, and a description — in the words buyers and AI shopping agents
   already type into search. It does not invent a price, dimensions,
   materials, or an age it cannot see.
3. **eBay grounds it.** The same photo goes to eBay's official
   `search_by_image` endpoint, which returns live comparable listings —
   real titles and real asking prices for visually similar pieces.
4. **Draft out.** One Markdown draft lands next to the photo: the listing,
   the comparable listings, and the price range they support.

## Why the comps matter: mislabeling

Marketplace listings for these textiles are routinely mislabeled — a suzani
listed as a "tapestry," a Kantha listed as a "quilt." Keyword search can't
find those; image search can, because it matches the piece, not the words.

That cuts both ways, and the agent uses both:

- **For selling:** the listing uses the *correct* term (suzani, Kantha) plus
  the terms buyers actually search — including the common wrong ones — so
  the piece is findable either way.
- **For pricing:** the price range comes from live listings of similar
  pieces, not from a guess.

In the first live test (Nov 25, 2026), one photo of a vintage Uzbek suzani
returned 10 comparable eBay listings, on-target prices $150–$499 — two of
them with the suzani mislabeled as a "tapestry" in the title.

## The same agent, buying

Run the pipeline the other way and it's a buying tool. People already walk
garage sales and estate sales photographing pieces and asking an AI
assistant what they're looking at and what it sells for. This agent is that
workflow, productized: photo in, description and comparable prices out —
the question just flips from "what do I list it for?" to "what do I pay?"

That's where the mislabeling cuts hardest. A suzani on a folding table
tagged "blanket, $20" is invisible to keyword search; the image search
finds what it actually is and what it actually sells for. For anyone
sourcing vintage pieces, it's the mislabel hunt with the price already
on it.

## Honest limits

The model's tradition and motif labels are **drafts**. They come from
web-scale training data with no verifier — mislabeled photos are common in
this niche, so a label can be a confident guess. Nothing this agent writes
publishes itself: **a human verifies every listing before it goes live.**
The agent drafts fast; the seller stays the authority.

## Cost

One listing costs about **$0.0003** at Muse Ember prices ($0.10 / $0.50 per
1M input/output tokens) — a photo in, a structured listing out, in about
3 seconds. The eBay image search is free under a developer account.

## Usage

```bash
export META_API_KEY=...        # Meta Model API key
export EBAY_CLIENT_ID=...      # eBay developer app: App ID (Client ID)
export EBAY_CLIENT_SECRET=...  # eBay developer app: Cert ID (Client Secret)

python3 listing_agent.py path/to/photo.jpg
```

Writes `photo-listing.md` (the draft) and `photo-listing.json` (the raw
Ember + eBay responses) next to the photo, and prints the listing title and
the comp price range. Keys are read from environment variables only and are
never written to any file or output. The eBay step is optional — without
eBay keys the agent still writes the listing draft, without comps.

## Hackathon environment note

During the hackathon, the development VM's network egress blocks
`api.meta.ai`, so the Ember calls were executed through a Modal relay with
the key held as a Modal secret. The code in this repo calls the Meta Model
API directly, the normal way — the relay was an environment workaround, not
part of the design.

## License

Apache-2.0. See [LICENSE](LICENSE).
