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

## Current project track

This project follows Track A: a literature-grounded evidence and
experimental-design MVP.

The application separates:

1. direct literature evidence;
2. normalized or derived values;
3. similar-formulation analogies;
4. DOE experimental candidates; and
5. future model predictions.

The Week 5 application will not claim prospective biological validation,
unseen-cell prediction, a universally best formulation, or in-vivo
cell-type targeting.

COMET/neocloud work is an optional Day 25 feasibility exercise and is not
required for the main application.


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
