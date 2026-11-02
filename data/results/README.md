# Election results

`senate_2026.json` is written by `scripts/fetch_results.py` from the Wikipedia
race articles after polls close. Do not edit it by hand.

To correct or add a result, create `senate_2026_manual.json` next to it:

```json
{
  "results": {
    "Alaska": {
      "winner": "Dan Sullivan", "winner_party": "R",
      "dem_candidate": "Mary Peltola", "rep_candidate": "Dan Sullivan",
      "dem_pct": 47.9, "rep_pct": 52.1, "margin": -4.2,
      "total_votes": 0, "note": "final RCV round, AK Division of Elections"
    }
  }
}
```

`margin` is Dem − Rep in percentage points. Manual entries override the
scraped ones state by state; the next scoring run picks them up.
