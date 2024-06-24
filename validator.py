import pandas as pd
import json
import re
import numpy as np
from datetime import datetime
import sys


general = True # this allows rules with this condition to run on all rows

# TODO add testing for standalone rules
# Assuming the business rules JSON and Excel file are properly formatted and located.
# Load business rules from JSON
with open('business_rules_compiled.json', 'r') as file:
    rules = json.load(file)

# Load the Excel file
sheet_name = 'SOURCE DATA'
#sheet_name = 'Master Inventory'
df = pd.read_excel('DB_example_slim_full.xlsx', sheet_name=sheet_name)

# Define a dictionary to map old column names to new column names
rename_dict = {
    'Planned duration Budget support component (years)': 'Planned duration of the BS component',
    'CALCUL for RIO commitment': 'CALCUL fopr RIO commitment',
    # Add more columns as needed
}

# Rename the columns in the DataFrame
df = df.rename(columns=rename_dict)

#df = pd.read_excel('test_2022.xlsx', sheet_name=sheet_name)

# Helper function to check if value matches any pattern in a list
def matches_any_pattern(value, patterns):
    for pattern in patterns:
        if re.match(pattern, str(value)):
            return True
    return False

#  Function to validate individual fields in a row
def validate_field(field_name, value, rule):
    errors = []
    # Check for invalid values
    if "invalid_values" in rule and str(value) in rule["invalid_values"]:
        errors.append(f"{field_name} contains a disallowed value: {value}")
    # Check for valid values
    if "valid_values" in rule and value not in rule["valid_values"]:
        errors.append(f"{field_name} contains an invalid value: {value}")
    # Check that if empty
    if rule.get("empty_allowed") is False and pd.isnull(value):
        errors.append(f"{field_name} cannot be empty")
    # Check that it is a valid number
    if rule.get("type") == "numeric":
        numeric_value = pd.to_numeric(value, errors='coerce')
        if pd.isnull(numeric_value):
            errors.append(f"{field_name} must be numeric")
    # Check that it matches a pattern
    if "valid_patterns" in rule and not matches_any_pattern(value, rule["valid_patterns"]):
        errors.append(f'{field_name} does not match required format: {value}')
    return errors


# Function to validate field row per row
def validate_row(row, rules):
    errors = {}
    for condition_rule in rules.get("conditional_rules", []):
        if eval(condition_rule["condition"]):
            condition_description = condition_rule["description"]
            for sub_rule in condition_rule["field_validations"]:
                for field_name in sub_rule["field_names"]:
                    value = row.get(field_name)
                    field_errors = validate_field(field_name, value, sub_rule)
                    if field_errors:
                        if condition_description not in errors:
                            errors[condition_description] = []
                        errors[condition_description] += [f'{field_name}: ' + "; ".join(field_errors)]
    return errors

# Group consistency check function
def check_group_consistency(df, group_by_columns, rule):
    inconsistency_reports = {}
    rule_description = rule["description"]

    # Check if the rule contains 'field_names' for typical consistency checks
    if "field_names" in rule:
        columns_to_check = rule["field_names"]
        sum_column = ""
        compare_column = ""
    else:# meaning it is a multi-row arithmetic check
        columns_to_check = []
        sum_column = rule["arithmetic_check"]["sum_column"]
        compare_column = rule["arithmetic_check"]["compare_column"]
        suppress_error_value = rule.get("no_error_value", "toniLbarrous") # "toniLbarrous" is like -99, it will never be in the database, so it will not suppress errors

    # Acceptable error percent, defaulting to 1e-6 (0.000001%) if not specified
    acceptable_error_percent = rule.get("acceptable_error_percent", 0.000001)

    if isinstance(group_by_columns, str):
        group_by_columns = [group_by_columns]

    def check_group(group):
        group_identifier_str = " & ".join([f"{col}: {group[col].iloc[0]}" for col in group_by_columns])
        errors = []  # Collect errors for the group here

        if "field_names" in rule:
            for col in columns_to_check:
                if group[col].nunique() > 1:
                    errors.append(f"Inconsistent {col} ({group[col].nunique()} unique values) in group")
            # After collecting all errors for the group, join them and append to inconsistency_reports
            if errors:  # Check if there are any errors collected
                error_msg = f"Grouped by {group_identifier_str}: " + "; ".join(errors)
                if rule_description not in inconsistency_reports:
                    inconsistency_reports[rule_description] = []
                inconsistency_reports[rule_description].append(error_msg)
        else:
            # Ensure the sum_column is numeric for the entire group
            group[sum_column] = pd.to_numeric(group[sum_column], errors='coerce')
            sum_value = group[sum_column].sum()

            # Ensure expected_value is numeric, coercing non-numeric to NaN
            expected_value_raw = group[compare_column].iloc[0]
            expected_value = pd.to_numeric(expected_value_raw, errors='coerce')

            if not pd.isnull(expected_value):
                # Calculate the percentage difference between sum_value and expected_value
                percent_difference = abs((sum_value - expected_value) / expected_value) * 100

                # Check if the percentage difference is within the acceptable error percent
                if percent_difference > acceptable_error_percent:
                    error_msg = f"Grouped by {group_identifier_str}: Sum of {sum_column} ({round(sum_value,3)}) does not match {compare_column} ({round(expected_value,3)}) within the acceptable error margin of {acceptable_error_percent}%. Difference: {round(percent_difference,3)}%"
                    if rule_description not in inconsistency_reports:
                        inconsistency_reports[rule_description] = []
                    inconsistency_reports[rule_description].append(error_msg)
            else:
                if expected_value_raw != suppress_error_value:
                    # Handle cases where expected_value cannot be converted to numeric
                    error_msg = f"Grouped by {group_identifier_str}: Expected value '{expected_value_raw}' in {compare_column} cannot be interpreted as numeric"
                    if rule_description not in inconsistency_reports:
                        inconsistency_reports[rule_description] = []
                    inconsistency_reports[rule_description].append(error_msg)

    df_grouped = df.groupby(group_by_columns, as_index=False)

    if "field_names" in rule:
        df_grouped[group_by_columns + columns_to_check].apply(check_group)
    else:
        df_grouped[group_by_columns + [sum_column, compare_column]].apply(check_group)

    return inconsistency_reports if inconsistency_reports else {rule_description: ["No inconsistencies found"]}

# conditional group concistency
def check_conditional_sum_consistency(df, rule):
    error_messages = []
    group_by_columns = rule["group_by_columns"]
    sum_column = rule["sum_column"]
    compare_column = rule["compare_column"]
    acceptable_error_percent = rule.get("acceptable_error_percent", 0.000001)

    # Dynamically evaluate the condition
    condition = rule["condition"]

    grouped = df.groupby(group_by_columns)

    for name, group in grouped:
        # Apply the condition to filter the DataFrame
        filtered_group = group[group.apply(lambda row: eval(condition, {}, {"row": row}), axis=1)]

        # Calculate sum of the filtered group
        sum_value = pd.to_numeric(filtered_group[sum_column], errors='coerce').sum()
        expected_value = pd.to_numeric(group[compare_column].iloc[0], errors='coerce')

        # Calculate percentage difference
        if not pd.isnull(expected_value) and expected_value != 0:
            percent_difference = abs((sum_value - expected_value) / expected_value) * 100
            if percent_difference > acceptable_error_percent:
                error_message = (
                    f"CRIS Decision No {name}: Sum of {sum_column} after filtering ({sum_value}) does not match "
                    f"{compare_column} ({expected_value}) within an acceptable error margin of {acceptable_error_percent}%.")
                error_messages.append(error_message)

    return error_messages


# mapping main SDGs check 1_O14
def validate_sdg_rule(df):
    errors = []
    for index, row in df.iterrows():
        main_sdg = row['Tranche or Indicator Main SDG in number']
        if isinstance(main_sdg, str) and main_sdg.startswith('SDG'):
            sdg_number = main_sdg[3:]  # Extract the number part of SDGX
            corresponding_sdg_column = f'SDG{sdg_number}'
            if sdg_number.isdigit() and 1 <= int(sdg_number) <= 17:
                if row[corresponding_sdg_column] != 2:
                    errors.append((index, f'Row {index + 2}: {corresponding_sdg_column} should have a value of 2 for {main_sdg}'))
            else:
                errors.append((index, f'Row {index + 2}: {main_sdg} is not a valid SDG number'))
    return errors


# Helper function to calculate the difference in years between two dates
def calculate_duration_in_years(start_date, end_date):
    if pd.isnull(start_date) or pd.isnull(end_date):
        return None
    # start_date = datetime.strptime(start_date, '%d/%m/%y')
    # end_date = datetime.strptime(end_date, '%d/%m/%y')
    return (end_date - start_date).days / 365.25


def parse_date_with_coercion(input_date):
    # Check if the input_date is pd.NA, None, or not a string
    if input_date is pd.NA or not isinstance(input_date, str) or input_date == '':
        # Return pd.NA (or np.nan, or None, depending on your preference)
        return None
    try:
        # Attempt to parse the date
        return datetime.strptime(input_date, '%d/%m/%y')
    except ValueError:
        # Coerce parsing errors to NA
        return None

# Standalone function to check for errors in "Actual duration of BS component (years)"
def check_actual_duration_errors(row):
    row = row.replace('-', pd.NA)
    actual_duration = row.get("Actual duration of BS component (years)")
    signature_date = row.get("Signature Date EU (dd/mm/yy)")
    last_disbursement_date = row.get("Actual last tranche disbursement date (dd/mm/yy)")

    # Ensure signature_date and last_disbursement_date are in datetime format if not already
    # This step may be unnecessary if your DataFrame always contains datetime objects in these columns
    # If they might be strings in some cases, you could include a condition to parse them only if they are strings
    # Example:
    if not isinstance(signature_date, datetime):
        signature_date = parse_date_with_coercion(signature_date)
    if not isinstance(last_disbursement_date, datetime):
        last_disbursement_date = parse_date_with_coercion(last_disbursement_date)


    if isinstance(last_disbursement_date, datetime):
        calculated_duration = calculate_duration_in_years(signature_date, last_disbursement_date)

        # Assuming a small tolerance for floating point arithmetic errors
        tolerance = 0.02
        if isinstance(calculated_duration, (int, float)) and isinstance(actual_duration, (int, float)):
            if not np.isclose(actual_duration, calculated_duration, atol=tolerance):
                return f"Actual duration of BS component (years) error: Expected {calculated_duration:.2f} years, found {actual_duration} years."
    return None

def validate_fiscal_quarter_and_year_datetime(df):
    errors = []
    for index, row in df.iterrows():
        actual_date = row["Actual disbursement date (dd/mm/yy)"]
        fiscal_quarter = row["Fiscal Quarter of Actual Disbursement"]
        fiscal_year = row["Fiscal Year of Actual Disbursement"]

        # Ensure the actual disbursement date is a datetime object
        if not pd.isnull(actual_date) and isinstance(actual_date, datetime):
            # Determine the correct fiscal quarter
            month = actual_date.month
            if 1 <= month <= 3:
                correct_fiscal_quarter = "Q1"
            elif 4 <= month <= 6:
                correct_fiscal_quarter = "Q2"
            elif 7 <= month <= 9:
                correct_fiscal_quarter = "Q3"
            elif 10 <= month <= 12:
                correct_fiscal_quarter = "Q4"
            else:
                correct_fiscal_quarter = None  # This should never happen

            # Check if the fiscal quarter and year match
            if fiscal_quarter != correct_fiscal_quarter:
                errors.append(f"Row {index + 2}: Incorrect Fiscal Quarter. Expected {correct_fiscal_quarter}, found {fiscal_quarter}")

            # Extract year from the date and format it to match the fiscal year format
            correct_fiscal_year = actual_date.year
            if fiscal_year != correct_fiscal_year:
                errors.append(f"Row {index + 2}: Incorrect Fiscal Year. Expected {correct_fiscal_year}, found {fiscal_year}")
        # else:
        #     errors.append(f"Row {index + 2}: 'Actual disbursement date (dd/mm/yy)' is not a valid datetime object")

    return errors

def check_amendments_in_fa_consistency(df):
    """
    Check if, for each group of 'CRIS Decision No', having at least one '1' in
    'Indicator or target change through Rider 0 or 1' requires all entries in
    'Amendments in FA (0 no, 1 yes)' to be '1'.
    """
    error_messages = []

    # Group by 'CRIS Decision No'
    grouped_df = df.groupby('CRIS Decision No')

    for name, group in grouped_df:
        # Check if there's at least one '1' in 'Indicator or target change through Rider 0 or 1'
        if group['Indicator or target change through Rider 0 or 1'].eq(1).any():
            # Verify all values in 'Amendments in FA (0 no, 1 yes)' are '1'
            if not group['Amendments in FA (0 no, 1 yes)'].eq(1).all():
                error_messages.append(f"CRIS Decision No '{name}' fails the rule: Not all 'Amendments in FA (0 no, 1 yes)' values are '1' when required.")

    return error_messages

def check_value_vt_consistency_and_sum_rule(df):
    grouped = df.groupby('CRIS Decision No')

    error_messages = []

    for name, group in grouped:
        if group['Value VT only'].nunique() > 1:
            error_messages.append(f'CRIS Decision No {name}: "Value VT only" values are not consistent.')
            continue

        value_vt_only = pd.to_numeric(group['Value VT only'].iloc[0], errors='coerce') if not group['Value VT only'].empty else 0

        vt_rows = group[(group['FT or VT'] == 'VT')].copy()
        vt_rows['Final Planned Amount Tranche in €M'] = pd.to_numeric(vt_rows['Final Planned Amount Tranche in €M'], errors='coerce')

        # New approach: Sum distinct "Final Planned Amount Tranche in €M" for each distinct "Tranche"
        total_sum = 0
        for tranche_name, tranche_group in vt_rows.groupby('Tranche'):
            distinct_amounts = tranche_group['Final Planned Amount Tranche in €M'].drop_duplicates()
            total_sum += distinct_amounts.sum()
        if total_sum != 0:
            if not np.isclose(value_vt_only, total_sum, atol=1e-5):
                error_messages.append(f'CRIS Decision No {name}: "Value VT only" ({value_vt_only:.2f}) does not equal the sum of distinct "Final Planned Amount Tranche in €M" values for each distinct "Tranche" in VT ({total_sum:.2f}).')

    return error_messages

def check_tranche_sum_equals_final_amount_bs(df):
    grouped_by_cris = df.groupby('CRIS Decision No')

    error_messages = []

    for cris_name, cris_group in grouped_by_cris:
        if cris_group['Final Amount BS in millions of Euros'].nunique() > 1:
            error_messages.append(f'CRIS Decision No {cris_name}: "Final Amount BS in millions of Euros" values are not consistent.')
            continue

        # Corrected approach for handling NaN after conversion to numeric
        final_amount_bs = pd.to_numeric(cris_group['Final Amount BS in millions of Euros'].iloc[0], errors='coerce')
        final_amount_bs = 0 if np.isnan(final_amount_bs) else final_amount_bs

        tranche_sum = 0
        for tranche, tranche_group in cris_group.groupby('Tranche'):
            # Convert to numeric; directly handle NaN by converting to 0
            first_row_value = pd.to_numeric(tranche_group['Final Planned Amount Tranche in €M'].iloc[0], errors='coerce')
            first_row_value = 0 if np.isnan(first_row_value) else first_row_value

            tranche_sum += first_row_value

        if not np.isclose(tranche_sum, final_amount_bs, atol=0.01):
            error_messages.append(f'CRIS Decision No {cris_name}: The sum of the first row values of "Final Planned Amount Tranche in €M" for each "Tranche" ({tranche_sum}) does not equal the "Final Amount BS in millions of Euros" ({final_amount_bs}).')

    return error_messages

def check_disbursement_dates_consistency(df):
    errors = []
    # Replace "-" with NaN to simplify processing
    df = df.replace('-', pd.NA)

    # Convert date columns to datetime, errors='coerce' will handle any invalid date formats by converting them to NaT
    df["Actual last tranche disbursement date (dd/mm/yy)"] = pd.to_datetime(df["Actual last tranche disbursement date (dd/mm/yy)"], errors='coerce', dayfirst=True)
    df["Actual disbursement date (dd/mm/yy)"] = pd.to_datetime(df["Actual disbursement date (dd/mm/yy)"], errors='coerce', dayfirst=True)

    grouped = df.groupby("CRIS Decision No")

    for name, group in grouped:
        # Filter out NA and NaT, then get unique non-NA dates in "Actual disbursement date (dd/mm/yy)"
        non_na_disbursement_dates = group["Actual disbursement date (dd/mm/yy)"].dropna().unique()
        non_na_final_disbursement_dates = group["Actual last tranche disbursement date (dd/mm/yy)"].dropna().unique()

        if non_na_final_disbursement_dates.size > 0:
            # Proceed only if there's at least one non-NA and non-NaT value
            if non_na_disbursement_dates.size > 0:
                most_recent_date = non_na_disbursement_dates.max()

                # Check all "Actual last tranche disbursement date (dd/mm/yy)" against the most recent date
                last_tranche_date_consistent = group["Actual last tranche disbursement date (dd/mm/yy)"].dropna().nunique() == 1 \
                                               and group["Actual last tranche disbursement date (dd/mm/yy)"].dropna().iloc[0] == most_recent_date

                if not last_tranche_date_consistent:
                    errors.append(f'CRIS Decision No {name} has inconsistent "Actual last tranche disbursement date (dd/mm/yy)". Expected all to be {most_recent_date.strftime("%d/%m/%Y")}.')
    return errors

def check_status_bs_component(df):
    errors = []
    # Group by "CRIS Decision No"
    grouped = df.groupby('CRIS Decision No')
    for name, group in grouped:
        # Use pd.notna() to check for non-missing values and exclude specific unwanted values
        condition_met = group['Actual last tranche disbursement date (dd/mm/yy)'].apply(lambda x: pd.notna(x) and x not in ['-', '']).any()
        if condition_met:
            # Check if all "Status of BS component" in the group are 'closed'
            if not all(group['Status of BS component '] == 'All tranches paid'):
                errors.append(f'CRIS Decision No {name} should have "Status of BS component" as "All tranches paid" due to non-blank row in "Actual last tranche disbursement date (dd/mm/yy)"')
    return errors


def validate_sector_code_consistency(df):
    """
    Validates that the first three digits of 'Level 2 Sector CRS code (5 digit code)' match the number in 'Level 1 Sector DAC 5 code' for each row.
    Args:
        df (pd.DataFrame): The DataFrame to validate.
    Returns:
        dict: A dictionary containing row indices (starting from 1 for human readability) as keys and error messages as values.
    """
    error_log = {}
    for index, row in df.iterrows():
        sector_code_l1 = str(row['Level 1 Sector DAC 5 code'])
        sector_code_l2 = str(row['Level 2 Sector CRS code (5 digit code)'])

        # Check if the first three characters of Sector_Code_L2 match Sector_Code_L1
        if not sector_code_l2.startswith(sector_code_l1):
            error_msg = (f"Row {index + 2}: 'Level 2 Sector CRS code (5 digit code)' ({sector_code_l2}) does not start with "
                         f"the same digits as 'Level 1 Sector DAC 5 code' ({sector_code_l1}).")
            error_log[index + 2] = error_msg

    return error_log

def validate_arithmetic_operations(row, arithmetic_rules):
    errors = []
    for rule in arithmetic_rules:
        expected_column = rule["expected_column"]
        acceptable_error_percent = rule.get("acceptable_error_percent", 0)

        # Initialize total with the adjustment if specified, else 0
        adjustment = rule.get("adjustment", 0)
        total = adjustment

        # Handle addition, treating non-numeric values as 0
        for col in rule.get('add', []):
            value = pd.to_numeric(row[col], errors='coerce')
            total += 0 if pd.isnull(value) else value

        # Handle subtraction, treating non-numeric values as 0
        for col in rule.get('subtract', []):
            value = pd.to_numeric(row[col], errors='coerce')
            total -= 0 if pd.isnull(value) else value

        expected_value = pd.to_numeric(row[expected_column], errors='coerce')
        expected_value = 0 if pd.isnull(expected_value) else expected_value

        # Calculate absolute tolerance
        absolute_tolerance = abs(
            expected_value * acceptable_error_percent / 100) if acceptable_error_percent > 0 else 1e-5

        if not np.isclose(total, expected_value, atol=absolute_tolerance):
            error_msg = (f"Arithmetic validation failed for {expected_column}: "
                         f"Currently {round(expected_value,3)}, but should be {round(total,3)}. "
                         f"Acceptable error margin: {acceptable_error_percent}%. "
                         f"Difference: {round(abs(total - expected_value),3)} against tolerance: {round(absolute_tolerance,3)}")
            errors.append(error_msg)

    return errors
def check_columns_existence(df, rules):
    # Extract column names from conditional_rules
    conditional_columns = [
        field_name
        for rule in rules.get("conditional_rules", [])
        for validation in rule["field_validations"]
        for field_name in validation["field_names"]
    ]

    # Extract column names from group_consistency_rules
    consistency_columns = [
        field_name
        for rule in rules.get("group_consistency_rules", [])
        for field_name in rule["field_names"]
    ]

    # Combine and deduplicate the list of all column names
    all_columns = list(set(conditional_columns + consistency_columns))

    # Check if each column exists in the DataFrame
    missing_columns = [column for column in all_columns if column not in df.columns]

    # Report missing columns and raise an exception
    if missing_columns:
        raise ValueError(f"Missing columns in DataFrame: {missing_columns}. Please add these columns and try again.")
    else:
        print("All columns are present in the DataFrame.")


# Main function to orchestrate the validation process with single-line error reporting
def main():
    condition_errors = {}
    for index, row in df.iterrows():
        row_errors = validate_row(row, rules)
        for condition, errors in row_errors.items():
            if condition not in condition_errors:
                condition_errors[condition] = []
            condition_errors[condition].append((index, errors))

    # Error reporting with single-line aggregation
    if not condition_errors:
        print("No row-wise field errors found. Data validation successful.")
    else:
        print("Errors found, organized by condition:")
        for condition, errors_list in condition_errors.items():
            print(f"Condition '{condition}':")
            for index, errors in errors_list:
                row_errors_msg = f"Row {index + 2}: " + "; ".join(errors)
                print(f"  - {row_errors_msg}")

    # Group consistency checks - Updated to accommodate changes
    for consistency_rule in rules.get("group_consistency_rules", []):
        # Pass the entire rule as a parameter
        inconsistency_reports = check_group_consistency(df, consistency_rule["group_by_columns"], consistency_rule)
        for condition, errors in inconsistency_reports.items():
            if errors != ["No inconsistencies found"]:
                print(f"{condition}: Errors found")
                for error in errors:
                    print(f"  - {error}")
            else:
                print(f"{condition}: No inconsistencies found.")

    # Arithmetic errors check remains unchanged
    arithmetic_errors = {}
    arithmetic_rules = rules.get("arithmetic_rules", [])
    for index, row in df.iterrows():
        row_errors = validate_arithmetic_operations(row, arithmetic_rules)
        if row_errors:
            arithmetic_errors[index] = row_errors

    # Report arithmetic errors
    if arithmetic_errors:
        print("Arithmetic errors found:")
        for index, errors in arithmetic_errors.items():
            print(f"  - Row {index + 2}: " + "; ".join(errors))
    else:
        print("No arithmetic errors found.")

    # conditional group concistency
    conditional_sum_rules = rules.get("conditional_sum_consistency_rules", [])

    for rule in conditional_sum_rules:
        error_messages = check_conditional_sum_consistency(df, rule)
        if error_messages:
            print(f"Errors for rule {rule['ID']} - {rule['description']}:")
            for message in error_messages:
                print(f"  - {message}")
        else:
            print(f"No errors for rule {rule['ID']} - {rule['description']}.")

    # Report main SDG mapping errors
    sdg_rule_errors = validate_sdg_rule(df)
    if sdg_rule_errors:
        print("SDG Rule Validation Errors:")
        for error in sdg_rule_errors:
            print(f"  - {error[1]}")
    else:
        print("No SDG Rule Validation Errors.")

    # Check for Actual duration errors
    actual_duration_errors = []
    for index, row in df.iterrows():
        error = check_actual_duration_errors(row)
        if error:
            actual_duration_errors.append((index, error))

    # Report Actual duration errors
    if actual_duration_errors:
        print("Actual duration of BS component (years) errors found:")
        for index, error in actual_duration_errors:
            print(f"  - Row {index + 2}: {error}")
    else:
        print("No errors found in 'Actual duration of BS component (years)'.")

    # Call to validate fiscal quarter and year based on datetime
    fiscal_errors = validate_fiscal_quarter_and_year_datetime(df)
    if fiscal_errors:
        print("Fiscal quarter and year validation errors found:")
        for error in fiscal_errors:
            print(f"  - {error}")
    else:
        print("No fiscal quarter or year validation errors found.")

    # Check for consistency regarding 'Amendments in FA'
    amendment_fa_errors = check_amendments_in_fa_consistency(df)
    if amendment_fa_errors:
        print("Errors found for 'Amendments in FA' consistency check:")
        for error in amendment_fa_errors:
            print(f"  - {error}")
    else:
        print("No errors found for 'Amendments in FA' consistency check.")

    # Validate "Value VT only" consistency and sum rule
    value_vt_errors = check_value_vt_consistency_and_sum_rule(df)
    if value_vt_errors:
        print("Errors found in 'Value VT only' consistency and sum check:")
        for error in value_vt_errors:
            print(f"  - {error}")
    else:
        print("No errors found in 'Value VT only' consistency and sum check.")

    # check for "Tranche" sum equals "Final Amount BS in millions of Euros"
    tranche_sum_errors = check_tranche_sum_equals_final_amount_bs(df)
    if tranche_sum_errors:
        print("Errors found in 'Tranche' sum and 'Final Amount BS in millions of Euros' check:")
        for error in tranche_sum_errors:
            print(f"  - {error}")
    else:
        print("No errors found in 'Tranche' sum and 'Final Amount BS in millions of Euros' check.")

    # disbursement dates consistency check
    disbursement_dates_errors = check_disbursement_dates_consistency(df)
    if disbursement_dates_errors:
        print("Disbursement dates consistency errors found:")
        for error in disbursement_dates_errors:
            print(f"  - {error}")
    else:
        print("No disbursement dates consistency errors found.")

    # check for "Status of BS component" based on the rule
    status_bs_component_errors = check_status_bs_component(df)
    if status_bs_component_errors:
        print("Errors found for 'Status of BS component':")
        for error in status_bs_component_errors:
            print(f"  - {error}")
    else:
        print("No errors found for 'Status of BS component'.")

    # Check that L1 and L2 sector codes are consistent
    sector_code_errors = validate_sector_code_consistency(df)
    # Output the errors, if any
    if sector_code_errors:
        print("Sector code consistency errors found:")
        for index, error_msg in sector_code_errors.items():
            print(f"  - {error_msg}")
    else:
        print("No sector code consistency errors found.")


#usage
# if __name__ == "__main__":
#     try:
#         # Load your DataFrame `df` and rules `rules` here
# # TODO       #check_columns_existence(df, rules)
#         main()  # Proceed with the rest of your validation and processing
#     except ValueError as e:
#         print(e)
#         # Exit the script or handle the missing columns as needed

if __name__ == "__main__":
    original_stdout = sys.stdout  # Save a reference to the original standard output

    with open('errors.txt', 'w') as f:
        sys.stdout = f  # Change the standard output to the file we created.
        try:
            # Load your DataFrame `df` and rules `rules` here
            # TODO: #check_columns_existence(df, rules)
            main()  # Proceed with the rest of your validation and processing
        except ValueError as e:
            print(e)  # This will go to errors.txt
        finally:
            sys.stdout = original_stdout  # Reset the standard output to its original value

    # Here you can do further processing or exit the script


