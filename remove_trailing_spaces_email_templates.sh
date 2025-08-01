#!/bin/bash

# Script to remove trailing spaces from empty lines in email templates
# Author: Generated script for Poweradmin project

# Set script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
EMAIL_TEMPLATES_DIR="$PROJECT_ROOT/templates/emails"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to display usage
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Remove trailing spaces from empty lines in email templates"
    echo ""
    echo "Options:"
    echo "  -h, --help     Show this help message"
    echo "  -n, --dry-run  Show what would be changed without making changes"
    echo "  -v, --verbose  Verbose output"
    echo ""
    echo "Examples:"
    echo "  $0              # Process all email templates"
    echo "  $0 --dry-run    # Preview changes without applying them"
    echo "  $0 --verbose    # Show detailed processing information"
}

# Initialize variables
DRY_RUN=false
VERBOSE=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            exit 0
            ;;
        -n|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        *)
            echo -e "${RED}Error: Unknown option '$1'${NC}" >&2
            usage
            exit 1
            ;;
    esac
done

# Function for verbose output
verbose_echo() {
    if [[ "$VERBOSE" == true ]]; then
        echo -e "$1"
    fi
}

# Check if email templates directory exists
if [[ ! -d "$EMAIL_TEMPLATES_DIR" ]]; then
    echo -e "${RED}Error: Email templates directory not found: $EMAIL_TEMPLATES_DIR${NC}" >&2
    exit 1
fi

echo -e "${GREEN}Processing email templates in: $EMAIL_TEMPLATES_DIR${NC}"

if [[ "$DRY_RUN" == true ]]; then
    echo -e "${YELLOW}DRY RUN MODE - No files will be modified${NC}"
fi

# Initialize counters
FILES_PROCESSED=0
FILES_MODIFIED=0
TOTAL_LINES_FIXED=0

# Find and process email template files
find "$EMAIL_TEMPLATES_DIR" -type f \( -name "*.twig" -o -name "*.html" -o -name "*.txt" \) | while read -r file; do
    FILES_PROCESSED=$((FILES_PROCESSED + 1))
    
    verbose_echo "${YELLOW}Processing: $file${NC}"
    
    # Check if file has trailing spaces on empty lines
    # Use grep to identify lines that contain only whitespace
    LINES_WITH_TRAILING_SPACES=$(grep -n '^[[:space:]]*$' "$file" | grep -v '^[0-9]*:$' | wc -l)
    
    if [[ $LINES_WITH_TRAILING_SPACES -gt 0 ]]; then
        echo -e "${YELLOW}Found $LINES_WITH_TRAILING_SPACES empty lines with trailing spaces in: $(basename "$file")${NC}"
        
        if [[ "$DRY_RUN" == false ]]; then
            # Create backup
            cp "$file" "$file.bak"
            
            # Remove trailing spaces from empty lines
            # This sed command matches lines with only whitespace and replaces them with empty lines
            sed -i '' 's/^[[:space:]]*$//' "$file"
            
            # Verify the change was successful
            NEW_LINES_WITH_TRAILING_SPACES=$(grep -n '^[[:space:]]*$' "$file" | grep -v '^[0-9]*:$' | wc -l)
            
            if [[ $NEW_LINES_WITH_TRAILING_SPACES -eq 0 ]]; then
                echo -e "${GREEN}✓ Fixed $LINES_WITH_TRAILING_SPACES lines in: $(basename "$file")${NC}"
                rm "$file.bak"  # Remove backup if successful
                FILES_MODIFIED=$((FILES_MODIFIED + 1))
                TOTAL_LINES_FIXED=$((TOTAL_LINES_FIXED + LINES_WITH_TRAILING_SPACES))
            else
                echo -e "${RED}✗ Failed to fix all trailing spaces in: $(basename "$file")${NC}" >&2
                mv "$file.bak" "$file"  # Restore backup
            fi
        else
            echo -e "${YELLOW}Would fix $LINES_WITH_TRAILING_SPACES lines in: $(basename "$file")${NC}"
            TOTAL_LINES_FIXED=$((TOTAL_LINES_FIXED + LINES_WITH_TRAILING_SPACES))
        fi
    else
        verbose_echo "${GREEN}✓ No trailing spaces found in: $(basename "$file")${NC}"
    fi
done

# Display summary
echo ""
echo -e "${GREEN}=== SUMMARY ===${NC}"
echo "Files processed: $FILES_PROCESSED"

if [[ "$DRY_RUN" == true ]]; then
    echo "Files that would be modified: $FILES_MODIFIED"
    echo "Lines that would be fixed: $TOTAL_LINES_FIXED"
else
    echo "Files modified: $FILES_MODIFIED"
    echo "Lines fixed: $TOTAL_LINES_FIXED"
fi

if [[ $FILES_MODIFIED -gt 0 && "$DRY_RUN" == false ]]; then
    echo -e "${GREEN}All trailing spaces successfully removed from email templates!${NC}"
elif [[ $TOTAL_LINES_FIXED -eq 0 ]]; then
    echo -e "${GREEN}No trailing spaces found in any email templates.${NC}"
fi

exit 0