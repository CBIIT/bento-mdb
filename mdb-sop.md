# Metamodel Database SOPs

## Schedule
* **Production MDB**: updated monthly.
* **Development MDB**: updated as models/mappings/terminologies added or updated until *amount of time* before Prod MDB update schedule.
* **Model Updates**: model sources checked weekly for updates to model file(s). If source model in MDF, GH Action can trigger diff, update, & review immediately.
* **Backups**: MDB branches backed up regularly.

## Processes

### Adding new model to Development MDB
  1. Create new issue in `bento-mdb` repository to add model.
  2. Create new branch from `develop`: `feature/{#Issue}/add-{model handle}`.
  3. Get latest stable release of model file(s) from source.\
    a. If model source is not a CBIIT GitHub Repository, create a new CBIIT model repository.\
    b. If model file(s) are not in MDF format, create a script to convert the model to MDF and store both script and MDF file(s) in CBIIT model repository.
  4. Generate a Liquibase Changelog to add the model to an MDB.\
    a. Use `make_model_changelog.py` script from most recent version of `bento-meta` Python package with the inputs:\
      `mdf_files`: the latest MDF file(s) from step 3.\
      `model_handle`: name of model (e.g. 'GDC').\
      `author`: name/initials of person generating changelog.\
      `_commit`: GitHub reference to commit/release of latest MDF file(s) from step 1.\
      `config_file_path`: path to `changelog.ini` file in `bento-mdb` repository.\
      `output_file_path`: path for output file in `bento-mdb`. Path determined by type of data (model/mapping/terms) and model handle.\
    b. Store generated changelog in relevant directory in `bento-mdb`. 
  5. Review Liquibase Changelog for errors.\
    a. Manual review by Changlog author for any obvious issues.\
    b. Liquibase `updateSQL` command on **Dev-MDB** for dry run.
  6. Add new model to Development MDB.\
    a. Generate Pull Request from new Step 2 branch to `develop` branch.\
    b. Run `update` command on new Changelog to update **Dev-MDB**.\
    c. Merge Pull Request from 6a.
  7. Review new model in Devlopment MDB/Development STS.\
    a. If external source, author review to determine if nodes/edges/props/terms/etc. align with what is expected from MDF(s).\
    b. If internal source, contact & request Data SME review from relevant DC (preferred).\
    c. If review indicates errors exist, determine if curating what's been added or rolling back changes and generating new Changelog preferred depending on scope of changes.

### Updating existing model in Development MDB
  1. Create new issue in `bento-mdb` repository to update model.
  2. Create new branch from `develop`: `feature/{#Issue}/update-{model handle}`.
  3. Get previous and new stable releases of model file(s) from source.\
    a. If source model file(s) are not in MDF format, use conversion script in CBIIT model repository to convert the new model release to MDF and update CBIIT model repository with new MDF files.\
    b. Use ref from previous `_commit` or model release version to get files used to last update MDB with relevant models/mappings/terminology.
    b. Ensure previous and new releases clearly indicated to prevent confusion between the two.
  4. Generate a Liquibase Changelog to update the model in an MDB.\
    a. Use `make_diff_changelog.py` script from most recent version of `bento-meta` Python package with the inputs:\
      `old_mdf_files`: the previous MDF file(s) from step 3.\
      `new_mdf_files`: the latest MDF file(s) from step 3.\
      `model_handle`: name of model (e.g. 'GDC').\
      `author`: name/initials of person generating changelog.\
      `_commit`: GitHub reference to commit/release of latest MDF file(s) from step 1.\
      `config_file_path`: path to `changelog.ini` file in `bento-mdb` repository.\
      `output_file_path`: path for output file in `bento-mdb`. Path determined by type of data (model/mapping/terms) and model handle.\
    b. Store generated changelog in relevant directory in `bento-mdb`. 
  5. Review Liquibase Changelog for errors.\
    a. Manual review by Changlog author for any obvious issues.\
    b. Liquibase `updateSQL` command on **Dev-MDB** for dry run.
  6. Update model in Development MDB.\
    a. Generate Pull Request from new Step 2 branch to `develop` branch.\
    b. Run `update` command on new Changelog on **Dev-MDB** to update model.\
    c. Merge Pull Request from 6a.
  7. Review model in Devlopment MDB/Development STS.\
    a. If external source, author review to determine if nodes/edges/props/terms/etc. align with what is expected from new MDF(s)/diff summary.\
    b. If internal source, contact & request Data SME review from relevant DCC (preferred).\
    c. If review indicates errors exist, determine if curating what's been added or rolling back changes and generating new Changelog preferred depending on scope of changes. 

### Curating an MDB
  1. TBD

### Updating Production MDB
  1. Open PR from Dev into Prod\
    a. Summarize changes (added/removed/updated models/mappings/terminologies)
    b. Update docs with changes to "Current Projects"
  2. Ensure changes reviewed for accuracy
  3. Blue/Green Switch from Dev to Prod
  4. Merge PR
  5. New GH Tag/Release
    a. Add in GH
    b. Announce release/changes in relevant channels (slack/etc.)

## Conventions

### MDF
  * Contained in `model-desc` directory in CBIIT GitHub Repository
  * Separated into multiple files:
    * `model`: MDF Handle, Nodes, and Edges dictionaries.
    * `model-props`: MDF PropDefinitions dictionary.
    * `model-terms`: MDF Terms dictionary.
    * `model-mapping`: MDF mapping extension with Models and Props/Terms dictionaries.
  * Either `.yml` or `.yaml` extension okay but should be consistent across files.
  * Preface file names with the relevant model handle followed by a dash or not but should be consistent across files.

### Liquibase Changelog
  * New model/mapping/terminology: `{model handle}_changelog.xml`
  * Updated model/mapping/terminology: `{model handle}diff_changelog_{ref}.xml`, where {ref} is the relevant GitHub release, tag, or commit with the updated MDFs.
