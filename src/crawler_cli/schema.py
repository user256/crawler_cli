"""Schema.org structured data extraction and parsing."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag


def create_schema_content_hash(schema_data: dict[str, Any]) -> str:
    """Create a SHA256 hash of normalized schema content for deduplication."""
    # Normalize the data by removing variable fields that don't affect uniqueness
    normalized = normalize_for_hashing(schema_data)
    
    # Convert to JSON with sorted keys for consistent hashing
    content = json.dumps(normalized, sort_keys=True, separators=(',', ':'))
    
    # Create SHA256 hash
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def normalize_for_hashing(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize schema data for consistent hashing by removing variable fields."""
    if not isinstance(data, dict):
        return data
    
    normalized = data.copy()
    
    # Remove fields that vary but don't affect schema uniqueness
    fields_to_remove = [
        '@id',           # IDs are often auto-generated
        'discovered_at', # Timestamps
        'created_at',    # Timestamps
        'updated_at',    # Timestamps
        'position',      # Position on page
        'url',           # URL references
        'mainEntityOfPage',  # Page-specific references
        'isPartOf',      # Page-specific references
    ]
    
    for field in fields_to_remove:
        normalized.pop(field, None)
    
    # Recursively normalize nested objects
    for key, value in normalized.items():
        if isinstance(value, dict):
            normalized[key] = normalize_for_hashing(value)
        elif isinstance(value, list):
            normalized[key] = [
                normalize_for_hashing(item) if isinstance(item, dict) else item
                for item in value
            ]
    
    return normalized


def extract_schema_data(html: str, base_url: str) -> list[dict[str, Any]]:
    """
    Extract all structured data from HTML.
    Returns a list of schema data dictionaries.
    """
    soup = BeautifulSoup(html, 'html.parser')
    schema_data = []
    
    # Extract JSON-LD
    json_ld_data = extract_json_ld(soup, base_url)
    schema_data.extend(json_ld_data)
    
    # Extract Microdata
    microdata = extract_microdata(soup, base_url)
    schema_data.extend(microdata)
    
    # Extract RDFa
    rdfa_data = extract_rdfa(soup, base_url)
    schema_data.extend(rdfa_data)
    
    # Detect broken schema markup
    broken_schema = detect_broken_schema(soup, base_url)
    schema_data.extend(broken_schema)
    
    return schema_data


def extract_json_ld(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    """Extract JSON-LD structured data from script tags."""
    schema_data = []
    
    # Find all script tags with type="application/ld+json"
    script_tags = soup.find_all('script', type='application/ld+json')
    
    for i, script in enumerate(script_tags):
        try:
            # Parse JSON content
            json_content = script.string.strip() if script.string else ""
            if not json_content:
                continue
                
            # Handle both single objects and arrays
            try:
                data = json.loads(json_content)
            except json.JSONDecodeError as e:
                schema_data.append({
                    'format': 'json-ld',
                    'type': 'InvalidJSON',
                    'raw_data': json_content,
                    'parsed_data': None,
                    'position': i,
                    'is_valid': False,
                    'validation_errors': [f"JSON decode error: {str(e)}"]
                })
                continue
            
            # Handle arrays of schema objects
            if isinstance(data, list):
                for j, item in enumerate(data):
                    schema_items = process_json_ld_item(item, json_content, i * 100 + j, base_url)
                    schema_data.extend(schema_items)
            else:
                # Single schema object
                schema_items = process_json_ld_item(data, json_content, i, base_url)
                schema_data.extend(schema_items)
                    
        except Exception as e:
            schema_data.append({
                'format': 'json-ld',
                'type': 'ParseError',
                'raw_data': str(script),
                'parsed_data': None,
                'position': i,
                'is_valid': False,
                'validation_errors': [f"Parse error: {str(e)}"]
            })
    
    return schema_data


def process_json_ld_item(data: dict[str, Any], raw_json: str, position: int, base_url: str) -> list[dict[str, Any]]:
    """Process a single JSON-LD item and extract schema types. Returns a list of schema items."""
    if not isinstance(data, dict):
        return []
    
    schema_items = []
    
    # Handle @graph structure (array of schema objects)
    if '@graph' in data and isinstance(data['@graph'], list):
        for i, graph_item in enumerate(data['@graph']):
            if isinstance(graph_item, dict):
                item_result = process_single_schema_item(graph_item, raw_json, f"{position}-{i}", base_url)
                if item_result:
                    schema_items.append(item_result)
        return schema_items
    
    # Handle single schema object
    item_result = process_single_schema_item(data, raw_json, position, base_url)
    if item_result:
        schema_items.append(item_result)
    
    return schema_items


def process_single_schema_item(data: dict[str, Any], raw_json: str, position: str, base_url: str) -> dict[str, Any] | None:
    """Process a single schema item and extract schema type."""
    if not isinstance(data, dict):
        return None
    
    # Extract @type or determine type from context
    schema_type = data.get('@type', 'Unknown')
    
    # Clean up the type (remove schema.org prefix if present)
    if isinstance(schema_type, str):
        schema_type = schema_type.replace('https://schema.org/', '').replace('http://schema.org/', '')
    elif isinstance(schema_type, list) and schema_type:
        # Handle multiple types - use the first one
        schema_type = str(schema_type[0]).replace('https://schema.org/', '').replace('http://schema.org/', '')
    
    # Normalize and validate the data
    normalized_data = normalize_schema_data(data, base_url)
    validation_errors, severity = validate_schema_data(normalized_data, schema_type)
    
    # Create content hash for deduplication
    content_hash = create_schema_content_hash(normalized_data) if normalized_data else ""
    
    return {
        'format': 'json-ld',
        'type': schema_type,
        'raw_data': raw_json,
        'parsed_data': json.dumps(normalized_data) if normalized_data else None,
        'position': position,
        'is_valid': len(validation_errors) == 0,
        'validation_errors': validation_errors,
        'severity': severity,
        'content_hash': content_hash
    }


def extract_microdata(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    """Extract microdata structured data."""
    schema_data = []
    
    # Find all elements with itemscope
    items = soup.find_all(attrs={'itemscope': True})
    
    for i, item in enumerate(items):
        try:
            # Extract itemtype
            itemtype = item.get('itemtype', '')
            if not itemtype:
                continue
            
            # Clean up the type
            schema_type = itemtype.replace('https://schema.org/', '').replace('http://schema.org/', '')
            
            # Extract properties
            properties = extract_microdata_properties(item, base_url)
            
            # Create normalized data structure
            normalized_data = {
                '@type': schema_type,
                **properties
            }
            
            validation_errors, severity = validate_schema_data(normalized_data, schema_type)
            
            schema_data.append({
                'format': 'microdata',
                'type': schema_type,
                'raw_data': str(item),
                'parsed_data': json.dumps(normalized_data),
                'position': i,
                'is_valid': len(validation_errors) == 0,
                'validation_errors': validation_errors,
                'severity': severity
            })
            
        except Exception as e:
            schema_data.append({
                'format': 'microdata',
                'type': 'ParseError',
                'raw_data': str(item),
                'parsed_data': None,
                'position': i,
                'is_valid': False,
                'validation_errors': [f"Parse error: {str(e)}"]
            })
    
    return schema_data


def extract_microdata_properties(item: Tag, base_url: str) -> dict[str, Any]:
    """Extract properties from a microdata item."""
    properties = {}
    
    # Find all itemprop elements within this item
    prop_elements = item.find_all(attrs={'itemprop': True})
    
    for prop in prop_elements:
        prop_name = prop.get('itemprop', '')
        if not prop_name:
            continue
        
        # Extract the value
        if prop.name in ['img', 'audio', 'video', 'source']:
            # Media elements - get src
            value = prop.get('src', '')
        elif prop.name == 'a':
            # Links - get href
            value = prop.get('href', '')
        elif prop.name == 'meta':
            # Meta tags - get content
            value = prop.get('content', '')
        elif prop.name == 'time':
            # Time elements - get datetime or text
            value = prop.get('datetime', prop.get_text(strip=True))
        else:
            # Other elements - get text content
            value = prop.get_text(strip=True)
        
        # Convert relative URLs to absolute
        if isinstance(value, str) and value.startswith('/'):
            value = urljoin(base_url, value)
        
        # Handle multiple properties with same name
        if prop_name in properties:
            if not isinstance(properties[prop_name], list):
                properties[prop_name] = [properties[prop_name]]
            properties[prop_name].append(value)
        else:
            properties[prop_name] = value
    
    return properties


def extract_rdfa(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    """Extract RDFa structured data."""
    schema_data = []
    
    # Find all elements with typeof
    items = soup.find_all(attrs={'typeof': True})
    
    for i, item in enumerate(items):
        try:
            # Extract typeof
            typeof = item.get('typeof', '')
            if not typeof:
                continue
            
            # Clean up the type
            schema_type = typeof.replace('https://schema.org/', '').replace('http://schema.org/', '')
            
            # Extract properties
            properties = extract_rdfa_properties(item, base_url)
            
            # Create normalized data structure
            normalized_data = {
                '@type': schema_type,
                **properties
            }
            
            validation_errors, severity = validate_schema_data(normalized_data, schema_type)
            
            schema_data.append({
                'format': 'rdfa',
                'type': schema_type,
                'raw_data': str(item),
                'parsed_data': json.dumps(normalized_data),
                'position': i,
                'is_valid': len(validation_errors) == 0,
                'validation_errors': validation_errors,
                'severity': severity
            })
            
        except Exception as e:
            schema_data.append({
                'format': 'rdfa',
                'type': 'ParseError',
                'raw_data': str(item),
                'parsed_data': None,
                'position': i,
                'is_valid': False,
                'validation_errors': [f"Parse error: {str(e)}"]
            })
    
    return schema_data


def extract_rdfa_properties(item: Tag, base_url: str) -> dict[str, Any]:
    """Extract properties from an RDFa item."""
    properties = {}
    
    # Find all elements with property within this item
    prop_elements = item.find_all(attrs={'property': True})
    
    for prop in prop_elements:
        prop_name = prop.get('property', '')
        if not prop_name:
            continue
        
        # Clean up property name
        prop_name = prop_name.replace('https://schema.org/', '').replace('http://schema.org/', '')
        
        # Extract the value
        if prop.name in ['img', 'audio', 'video', 'source']:
            # Media elements - get src
            value = prop.get('src', '')
        elif prop.name == 'a':
            # Links - get href
            value = prop.get('href', '')
        elif prop.name == 'meta':
            # Meta tags - get content
            value = prop.get('content', '')
        elif prop.name == 'time':
            # Time elements - get datetime or text
            value = prop.get('datetime', prop.get_text(strip=True))
        else:
            # Other elements - get text content
            value = prop.get_text(strip=True)
        
        # Convert relative URLs to absolute
        if isinstance(value, str) and value.startswith('/'):
            value = urljoin(base_url, value)
        
        # Handle multiple properties with same name
        if prop_name in properties:
            if not isinstance(properties[prop_name], list):
                properties[prop_name] = [properties[prop_name]]
            properties[prop_name].append(value)
        else:
            properties[prop_name] = value
    
    return properties


def normalize_schema_data(data: dict[str, Any], base_url: str) -> dict[str, Any]:
    """Normalize schema data by converting relative URLs to absolute."""
    if not isinstance(data, dict):
        return data
    
    normalized = {}
    for key, value in data.items():
        if isinstance(value, str) and value.startswith('/'):
            # Convert relative URL to absolute
            normalized[key] = urljoin(base_url, value)
        elif isinstance(value, dict):
            # Recursively normalize nested objects
            normalized[key] = normalize_schema_data(value, base_url)
        elif isinstance(value, list):
            # Normalize list items
            normalized[key] = [
                normalize_schema_data(item, base_url) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            normalized[key] = value
    
    return normalized


def validate_schema_data(data: dict[str, Any], schema_type: str) -> tuple[list[str], str]:
    """Validate schema data and return (validation_errors, severity_level)."""
    errors = []
    severity = 'info'  # Default severity
    
    if not isinstance(data, dict):
        errors.append("Schema data must be an object")
        return errors, 'error'
    
    # Basic validation for common schema types
    if schema_type.lower() == 'article':
        if not data.get('headline'):
            errors.append("Article missing required 'headline' property")
            severity = 'error'
        if not data.get('author'):
            errors.append("Article missing required 'author' property")
            severity = 'error'
    
    elif schema_type.lower() == 'product':
        if not data.get('name'):
            errors.append("Product missing required 'name' property")
            severity = 'error'
        if not data.get('offers'):
            errors.append("Product missing required 'offers' property")
            severity = 'error'
    
    elif schema_type.lower() == 'organization':
        if not data.get('name'):
            errors.append("Organization missing required 'name' property")
            severity = 'error'
    
    elif schema_type.lower() == 'breadcrumblist':
        if not data.get('itemListElement'):
            errors.append("BreadcrumbList missing required 'itemListElement' property")
            severity = 'error'
    
    elif schema_type.lower() == 'videoobject':
        # VideoObject validation for rich results
        if not data.get('name'):
            errors.append("VideoObject missing required 'name' property")
            severity = 'error'
        if not data.get('description'):
            errors.append("VideoObject missing required 'description' property")
            severity = 'error'
        
        # Check for common VideoObject issues that cause rich results failures
        if 'embedUrl' in data:
            embed_url = data['embedUrl']
            if '&#038;' in embed_url or '&amp;' in embed_url:
                errors.append("VideoObject embedUrl contains HTML entities that should be decoded")
                severity = 'warning'
            if not embed_url.startswith(('http://', 'https://')):
                errors.append("VideoObject embedUrl should be a valid HTTP/HTTPS URL")
                severity = 'error'
        
        if 'uploadDate' in data:
            upload_date = data['uploadDate']
            if not isinstance(upload_date, str) or len(upload_date) < 10:
                errors.append("VideoObject uploadDate should be a valid ISO 8601 date string")
                severity = 'warning'
        
        # Check for missing critical fields for rich results (these cause rich results to fail)
        if 'thumbnailUrl' not in data and 'image' not in data:
            errors.append("VideoObject missing 'thumbnailUrl' - CRITICAL for rich results eligibility")
            severity = 'critical'  # This prevents rich results
        
        # Check for recommended fields (these improve rich results but don't cause failure)
        if 'duration' not in data:
            errors.append("VideoObject missing 'duration' property (recommended for rich results)")
            if severity == 'info':
                severity = 'warning'
    
    # Validate URLs
    for key, value in data.items():
        if 'url' in key.lower() and isinstance(value, str):
            if not value.startswith(('http://', 'https://', '/')):
                errors.append(f"Invalid URL format for {key}: {value}")
                if severity == 'info':
                    severity = 'warning'
    
    return errors, severity


def identify_main_entity(schema_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Identify the main entity from a list of schema items."""
    # Priority order for main entities
    main_entity_priority = [
        'WebPage', 'Article', 'Product', 'Event', 'Recipe', 'Review',
        'LocalBusiness', 'Organization', 'Person', 'WebSite'
    ]
    
    for priority_type in main_entity_priority:
        for item in schema_items:
            if item.get('type', '').lower() == priority_type.lower():
                return item
    
    # If no priority entity found, return the first item
    return schema_items[0] if schema_items else None


def identify_schema_relationships(schema_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Identify relationships between schema items (main entity and properties)."""
    if not schema_items:
        return {'main_entity': None, 'properties': [], 'related_entities': []}
    
    main_entity = identify_main_entity(schema_items)
    if not main_entity:
        return {'main_entity': None, 'properties': [], 'related_entities': schema_items}
    
    # Common property types that are typically nested
    property_types = [
        'ImageObject', 'VideoObject', 'BreadcrumbList', 'Offer', 'AggregateRating',
        'Review', 'Author', 'Publisher', 'Organization'
    ]
    
    properties = []
    related_entities = []
    
    for item in schema_items:
        if item == main_entity:
            continue
            
        item_type = item.get('type', '').lower()
        if any(prop_type.lower() == item_type for prop_type in property_types):
            properties.append(item)
        else:
            related_entities.append(item)
    
    return {
        'main_entity': main_entity,
        'properties': properties,
        'related_entities': related_entities
    }


def get_schema_statistics(schema_data: list[dict[str, Any]]) -> dict[str, Any]:
    """Get statistics about extracted schema data."""
    stats = {
        'total_schemas': len(schema_data),
        'by_format': {},
        'by_type': {},
        'valid_count': 0,
        'invalid_count': 0,
        'validation_errors': []
    }
    
    for item in schema_data:
        # Count by format
        format_name = item.get('format', 'unknown')
        stats['by_format'][format_name] = stats['by_format'].get(format_name, 0) + 1
        
        # Count by type
        type_name = item.get('type', 'unknown')
        stats['by_type'][type_name] = stats['by_type'].get(type_name, 0) + 1
        
        # Count valid/invalid
        if item.get('is_valid', False):
            stats['valid_count'] += 1
        else:
            stats['invalid_count'] += 1
            errors = item.get('validation_errors', [])
            stats['validation_errors'].extend(errors)
    
    return stats


def detect_broken_schema(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    """
    Detect broken or malformed schema.org markup that our extraction missed.
    
    This function looks for:
    1. JSON-LD with @context and @type but malformed structure
    2. Microdata with itemscope but missing itemtype or malformed
    3. RDFa with vocab/typeof but malformed structure
    4. Schema.org URLs in content that aren't properly structured
    """
    broken_schema = []
    
    # 1. Check for malformed JSON-LD
    script_tags = soup.find_all('script', type='application/ld+json')
    for i, script in enumerate(script_tags):
        try:
            content = script.get_text(strip=True)
            if not content:
                continue
                
            # Check if it looks like JSON-LD but failed to parse
            if ('@context' in content and '@type' in content and 
                ('schema.org' in content or 'Schema.org' in content)):
                try:
                    json.loads(content)
                    # If it parses successfully, it's not broken
                    continue
                except json.JSONDecodeError:
                    # This is broken JSON-LD
                    broken_schema.append({
                        'format': 'json-ld',
                        'type': 'BrokenJSON-LD',
                        'raw_data': content,
                        'parsed_data': None,
                        'position': i,
                        'is_valid': False,
                        'validation_errors': ['Malformed JSON-LD: Invalid JSON syntax']
                    })
        except Exception as e:
            continue
    
    # 2. Check for malformed microdata
    # Look for itemscope without proper itemtype
    items_with_scope = soup.find_all(attrs={'itemscope': True})
    for i, item in enumerate(items_with_scope):
        itemtype = item.get('itemtype', '')
        if not itemtype or 'schema.org' not in itemtype:
            # This is broken microdata
            broken_schema.append({
                'format': 'microdata',
                'type': 'BrokenMicrodata',
                'raw_data': str(item)[:500],  # Limit size
                'parsed_data': None,
                'position': i,
                'is_valid': False,
                'validation_errors': ['Malformed microdata: itemscope without valid itemtype']
            })
    
    # 3. Check for malformed RDFa
    # Look for typeof without proper vocab or malformed structure
    items_with_typeof = soup.find_all(attrs={'typeof': True})
    for i, item in enumerate(items_with_typeof):
        typeof = item.get('typeof', '')
        vocab = item.get('vocab', '')
        
        if not typeof or ('schema.org' not in typeof and 'schema.org' not in vocab):
            # This is broken RDFa
            broken_schema.append({
                'format': 'rdfa',
                'type': 'BrokenRDFa',
                'raw_data': str(item)[:500],  # Limit size
                'parsed_data': None,
                'position': i,
                'is_valid': False,
                'validation_errors': ['Malformed RDFa: typeof without valid schema.org vocab']
            })
    
    # 4. Check for schema.org references in content that aren't structured
    # Look for schema.org URLs in text content, meta tags, or comments
    schema_url_pattern = re.compile(r'https?://schema\.org/[A-Za-z]+', re.IGNORECASE)
    
    # Check in meta tags
    meta_tags = soup.find_all('meta')
    for i, meta in enumerate(meta_tags):
        content = meta.get('content', '') or meta.get('property', '') or meta.get('name', '')
        if schema_url_pattern.search(str(content)):
            # Found schema.org reference in meta tag
            broken_schema.append({
                'format': 'meta',
                'type': 'BrokenMetaSchema',
                'raw_data': str(meta),
                'parsed_data': None,
                'position': i,
                'is_valid': False,
                'validation_errors': ['Schema.org reference in meta tag without proper structure']
            })
    
    # Check in comments
    comments = soup.find_all(string=lambda text: isinstance(text, str) and 'schema.org' in text)
    for i, comment in enumerate(comments):
        if schema_url_pattern.search(comment):
            broken_schema.append({
                'format': 'comment',
                'type': 'BrokenCommentSchema',
                'raw_data': comment[:200],  # Limit size
                'parsed_data': None,
                'position': i,
                'is_valid': False,
                'validation_errors': ['Schema.org reference in comment without proper structure']
            })
    
    # 5. Check for incomplete JSON-LD blocks
    # Look for script tags that contain partial JSON-LD
    all_scripts = soup.find_all('script')
    for i, script in enumerate(all_scripts):
        content = script.get_text(strip=True)
        if ('@context' in content or '@type' in content) and 'application/ld+json' not in script.get('type', ''):
            # Found JSON-LD-like content in non-JSON-LD script
            broken_schema.append({
                'format': 'json-ld',  # Use valid format for database constraint
                'type': 'BrokenScriptSchema',
                'raw_data': content[:500],  # Limit size
                'parsed_data': None,
                'position': i,
                'is_valid': False,
                'validation_errors': ['JSON-LD content in script tag without proper type attribute']
            })
    
    return broken_schema
