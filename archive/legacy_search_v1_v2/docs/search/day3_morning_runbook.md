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


## Query-version1 and 2 comparison

| Source | Cell | V1 matches | V2 matches | V2 first-page quality | Decision |
|---|---|---:|---:|---|---|
| PubMed | Hepatocyte |290|292|Keep|
| PubMed | Kupffer |39||42|Keep|
| PubMed | LSEC |12|16|Keep|
| PubMed | HSC |53|45|?????|Revert back to original|
| Europe PMC | Hepatocyte |287|289|Keep|
| Europe PMC | Kupffer |41|44|Keep|
| Europe PMC | LSEC |12|16|Keep|
| Europe PMC | HSC |57|46|Revert back to original|

## Version 2 official run

- Manifest version: `2.0.0`
- Previous version: `1.0.0`
- Reason for revision: sparse retrieval in one or more cell categories
- Run ID: run_20260721T160000+0800
- Run status: Completed
- Version 1 results preserved: yes
- Version 2 manifest snapshot verified: yes

PubMed >
    Hepatocyte > 292
    Kupffer > 42
    LSEC > 16
    HSC > 53

Europe PMC >
    Hepatocyte > 289
    Kupffer > 44
    LSEC > 16
    HSC > 57
