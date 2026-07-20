# Sensetime LNP

An AI-assisted, literature-grounded tool for finding and comparing LNP starting formulations for four liver cell types:

- Hepatocytes
- Kupffer cells
- Liver sinusoidal endothelial cells (LSECs)
- Hepatic stellate cells (HSCs)

The initial payload types are mRNA, siRNA, saRNA, and circRNA.

## Literature sources

- PubMed for citation and abstract retrieval
- Europe PMC for additional metadata and open-access identification
- PubMed Central for targeted full-text retrieval

## LLM provider

The project currently uses SenseNova through its OpenAI-compatible API endpoint.

## Day 1 status

- Python virtual environment created
- Dependencies installed
- Project folders created
- Git and GitHub configured
- Secrets stored in an ignored `.env` file
- SenseNova prompt test passed
- PubMed connection test passed
- Europe PMC connection test passed
- PMC full-text connection test passed

## Current limitations

The Day 1 scripts are connection tests only. They retrieve small temporary samples and do not create the final literature database. Collection, output standardization, deduplication, screening, and extraction validation will be implemented later.