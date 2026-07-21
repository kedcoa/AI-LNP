# Day 3 morning search run

## Search policy

- Manifest: `docs/search/query_manifest_v1.yaml`
- Manifest version: `1.0.0`
- Discovery sources: PubMed and Europe PMC
- Cell types: hepatocyte, Kupffer cell, LSEC, and HSC
- Equal retrieval cap: 100 records per cell per source
- PMC/open full text is reserved for later targeted retrieval.
- Search results are not considered eligible evidence until screening.

## Manual query checks

| Source | Cell | Reported matches | First-page relevance | Problems noticed | Decision |
|---|---|---:|---|---|---|
| PubMed | Hepatocyte | 290 |7| |NA| Keep | 
| PubMed | Kupffer | 39 | 6| Some is about how some tumors block LNPs from being delivered|Revise|
| PubMed | LSEC |12 |7 |Very very little sources|Revise|
| PubMed |HSC| 53| 8 | NA |Keep|  

| Europe PMC | Hepatocyte |287|7|Some are about reducing LNPs to liver cells|Revise |
| Europe PMC | Kupffer |41|6|Some are about the impact of PEG Lipids on LNPs|Revise |
| Europe PMC | LSEC |12|8|Not enough sources|Revise|
| Europe PMC | HSC |57|8|NA|Good|

## Official retrieval results

The automated search counts matched the manually observed counts for all eight
cell/source combinations.

- Run ID: 'run_20260721T144958+0800'
- Run status: `completed`
- Manifest version: `1.0.0`
- Retrieval cap per cell per source: `100`
- Detailed counts and provenance: `data/raw/searches/YYYY-MM-DD/run_TIMESTAMP/run_metadata.json`