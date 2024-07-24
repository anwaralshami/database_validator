# EU Budget Support Data Validation Script

## Overview

This script performs data validation on a dataset loaded from an Excel file, based on a set of business rules defined in a JSON file. The script checks for various types of inconsistencies and errors, including invalid values, arithmetic inconsistencies, group consistency, and more. The results of the validation are saved to an `errors.txt` file.

## Changes (24-07-2024)
- Enforced UTF-8 encoding of json files
- Streamlined console output
- Excluded deprecated rules

## Requirements

- Python 3.7+
- pandas
- numpy
- openpyxl

## Installation

1. Clone the repository or download the script files.
2. Install the required Python packages using pip:

```bash
pip install pandas numpy openpyxl
```

## Files

- `data_validation.py`: The main script containing all the validation functions and logic.
- `business_rules_compiled.json`: The JSON file containing the business rules for validation.
- `DB_example_slim_full.xlsx`: The Excel file containing the data to be validated.
- `errors.txt`: The output file where validation errors will be saved.

## Configuration

Before running the script, ensure that the paths to the JSON and Excel files are correct:

```python
# Load business rules from JSON
with open('business_rules_compiled.json', 'r', encoding='utf-8') as file:
    rules = json.load(file)

# Load the Excel file
sheet_name = 'SOURCE DATA'
df = pd.read_excel('DB_example_slim_full.xlsx', sheet_name=sheet_name)
```

## Usage

To run the script, execute the following command in your terminal:

```bash
python data_validation.py
```

The script will process the data and save any validation errors to `errors.txt`.

## Validation Functions

### Row-wise Field Validation

Validates individual fields in each row based on the rules defined in the JSON file. Checks for:
- Invalid values
- Valid values
- Empty fields
- Numeric type
- Pattern matching

### Group Consistency Check

Checks for consistency within groups of rows based on specified columns. Ensures that values within a group are consistent according to the rules.

### Arithmetic Operations Validation

Validates that the arithmetic operations on specified columns match expected values within an acceptable error margin.

### Special Validation Rules

Includes custom validation functions for specific checks such as:
- Main SDG mapping
- Actual duration of BS component
- Fiscal quarter and year based on disbursement dates
- Amendments in FA consistency
- Value VT only consistency and sum rule
- Tranche sum equals final amount BS
- Disbursement dates consistency
- Status of BS component based on disbursement date
- Sector code consistency

## Output

The validation errors are saved to `errors.txt` with detailed messages indicating the nature of the errors and the rows they occur in.

## Example Output

```txt
No row-wise field errors found. Data validation successful.
Condition 'Some Condition': Errors found
  - Row 3: Some field: Some error message
Group by Some Columns: Errors found
  - Grouped by some values: Some inconsistency message
...
```

## Customization

You can add or modify validation rules by editing the `business_rules_compiled.json` file. Ensure that the structure of the rules matches the expected format used in the script.

## Troubleshooting

If you encounter any issues, ensure that:
- The paths to the JSON and Excel files are correct.
- The required columns in the Excel file match those expected by the script.
- The JSON file is properly formatted.

For further assistance, you can refer to the comments within the script for detailed explanations of each function and validation rule.

## Disclaimer
This script is not intended for production use and was developed as a solution due to the unviability of using MS Access for this purpose. It was not a predetermined deliverable of the contract and is provided “as is” without any warranties or guarantees of its performance or reliability.

---

By following the instructions in this README, you should be able to set up, configure, and run the data validation script effectively. For any further questions or issues, please refer to the comments in the script or seek additional help from relevant resources.