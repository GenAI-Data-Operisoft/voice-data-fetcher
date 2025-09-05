from flask import Flask, request, jsonify
from flask_cors import CORS
import boto3
import base64
import json
import pandas as pd
import os
from datetime import datetime
import re
import logging

app = Flask(__name__)
CORS(app)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# AWS clients with error handling
try:
    session = boto3.Session(region_name=os.getenv('AWS_REGION', 'ap-south-1'))
    polly_client = session.client("polly")
    bedrock_client = session.client("bedrock-runtime")
except Exception as e:
    logger.error(f"AWS client initialization failed: {e}")
    polly_client = None
    bedrock_client = None

EXCEL_FILE = 'aws_community_visitors.xlsx'

class VoiceBotManager:
    def __init__(self):
        self.conversation_states = {
            'greeting': self.handle_greeting,
            'collect_name': self.handle_name_collection,
            'collect_company': self.handle_company_collection,
            'collect_email': self.handle_email_collection,
            'collect_phone': self.handle_phone_collection,
            'collect_country': self.handle_country_collection,
            'final_confirmation': self.handle_final_confirmation
        }
        
        # AI response patterns for better understanding
        self.positive_responses = [
            'yes', 'yeah', 'yep', 'yup', 'correct', 'right', 'true', 'confirm', 
            'ok', 'okay', 'perfect', 'exactly', 'absolutely', 'definitely', 
            'sure', 'good', 'great', 'fine', 'proceed', 'go ahead', 'continue',
            'that\'s right', 'sounds good', 'looks good', 'all good', 'excellent'
        ]
        
        self.negative_responses = [
            'no', 'nope', 'not', 'wrong', 'incorrect', 'false', 'negative',
            'not right', 'not correct', 'not perfect', 'that\'s wrong',
            'not good', 'bad', 'fix it', 'change it', 'redo', 'again'
        ]
        
        self.empty_user_data = {'name': '', 'company': '', 'email': '', 'phone': '', 'country': ''}
        
        # Country code mapping for smart formatting
        self.country_codes = {
            'usa': '+1', 'united states': '+1', 'america': '+1', 'us': '+1',
            'india': '+91', 'uk': '+44', 'united kingdom': '+44', 'britain': '+44',
            'canada': '+1', 'australia': '+61', 'germany': '+49', 'france': '+33',
            'japan': '+81', 'china': '+86', 'brazil': '+55', 'russia': '+7',
            'italy': '+39', 'spain': '+34', 'netherlands': '+31', 'sweden': '+46',
            'norway': '+47', 'denmark': '+45', 'finland': '+358', 'poland': '+48',
            'turkey': '+90', 'south africa': '+27', 'egypt': '+20', 'nigeria': '+234',
            'kenya': '+254', 'ghana': '+233', 'uae': '+971', 'saudi arabia': '+966',
            'singapore': '+65', 'malaysia': '+60', 'thailand': '+66', 'philippines': '+63',
            'indonesia': '+62', 'vietnam': '+84', 'south korea': '+82', 'taiwan': '+886'
        }
    
    def process_conversation(self, user_input, state, user_data, current_field, awaiting_confirmation):
        handler = self.conversation_states.get(state, self.handle_greeting)
        return handler(user_input, user_data, current_field, awaiting_confirmation)
    
    def handle_greeting(self, user_input, user_data, current_field, awaiting_confirmation):
        # Handle off-topic questions intelligently
        if self.is_off_topic_question(user_input):
            return self.handle_off_topic(user_input, user_data)
            
        positive_words = ['good', 'fine', 'great', 'well', 'excellent', 'awesome', 'fantastic', 'ok', 'okay']
        negative_words = ['not good', 'bad', 'terrible', 'awful', 'not well', 'sick', 'tired', 'stressed', 'not doing good', 'not great']
        
        user_lower = user_input.lower()
        
        if any(word in user_lower for word in negative_words):
            response = "I'm sorry to hear that. I hope our event can brighten your day! Let's get you registered. What's your name?"
            return {
                'bot_response': response,
                'new_state': 'collect_name',
                'updated_data': user_data,
                'current_field': 'name',
                'awaiting_confirmation': False
            }
        elif any(word in user_lower for word in positive_words):
            response = "Wonderful! Let's get started. What's your name?"
            return {
                'bot_response': response,
                'new_state': 'collect_name',
                'updated_data': user_data,
                'current_field': 'name',
                'awaiting_confirmation': False
            }
        else:
            response = "Hello! How are you doing today?"
            return {
                'bot_response': response,
                'new_state': 'greeting',
                'updated_data': user_data,
                'current_field': '',
                'awaiting_confirmation': False
            }
    
    def handle_name_collection(self, user_input, user_data, current_field, awaiting_confirmation):
        if awaiting_confirmation:
            if self.is_positive_response(user_input):
                response = f"Excellent! Which company do you work for, {user_data['name']}?"
                return {
                    'bot_response': response,
                    'new_state': 'collect_company',
                    'updated_data': user_data,
                    'current_field': 'company',
                    'awaiting_confirmation': False
                }
            elif self.is_negative_response(user_input):
                user_data['name'] = ''
                response = "No problem! Please tell me your correct name, or if you prefer, you can type it manually."
                return {
                    'bot_response': response,
                    'new_state': 'collect_name',
                    'updated_data': user_data,
                    'current_field': 'name',
                    'awaiting_confirmation': False,
                    'show_manual_input': True,
                    'manual_field': 'name'
                }
            else:
                response = "I didn't understand. Is your name correct? Please say yes or no."
                return {
                    'bot_response': response,
                    'new_state': 'collect_name',
                    'updated_data': user_data,
                    'current_field': 'name',
                    'awaiting_confirmation': True
                }
        else:
            name = self.extract_name(user_input)
            if name:
                user_data['name'] = name
                response = f"I heard your name as {name}. Is that correct?"
                return {
                    'bot_response': response,
                    'new_state': 'collect_name',
                    'updated_data': user_data,
                    'current_field': 'name',
                    'awaiting_confirmation': True
                }
            else:
                response = "I couldn't catch your name clearly. Could you please speak your name slowly, or type it manually?"
                return {
                    'bot_response': response,
                    'new_state': 'collect_name',
                    'updated_data': user_data,
                    'current_field': 'name',
                    'awaiting_confirmation': False,
                    'show_manual_input': True,
                    'manual_field': 'name'
                }
    
    def handle_company_collection(self, user_input, user_data, current_field, awaiting_confirmation):
        if awaiting_confirmation:
            if self.is_positive_response(user_input):
                response = f"Perfect! Now, what's your email address?"
                return {
                    'bot_response': response,
                    'new_state': 'collect_email',
                    'updated_data': user_data,
                    'current_field': 'email',
                    'awaiting_confirmation': False
                }
            elif self.is_negative_response(user_input):
                user_data['company'] = ''
                response = "Let me get that right. Which company do you work for? You can speak it or type it manually."
                return {
                    'bot_response': response,
                    'new_state': 'collect_company',
                    'updated_data': user_data,
                    'current_field': 'company',
                    'awaiting_confirmation': False,
                    'show_manual_input': True,
                    'manual_field': 'company'
                }
            else:
                response = "Is your company name correct? Please say yes or no."
                return {
                    'bot_response': response,
                    'new_state': 'collect_company',
                    'updated_data': user_data,
                    'current_field': 'company',
                    'awaiting_confirmation': True
                }
        else:
            company = self.extract_company(user_input)
            if company and len(company.strip()) > 1:
                user_data['company'] = company
                response = f"I heard your company as {company}. Is that correct?"
                return {
                    'bot_response': response,
                    'new_state': 'collect_company',
                    'updated_data': user_data,
                    'current_field': 'company',
                    'awaiting_confirmation': True
                }
            else:
                response = "Could you please tell me your company name clearly, or type it manually?"
                return {
                    'bot_response': response,
                    'new_state': 'collect_company',
                    'updated_data': user_data,
                    'current_field': 'company',
                    'awaiting_confirmation': False,
                    'show_manual_input': True,
                    'manual_field': 'company'
                }
    
    def handle_email_collection(self, user_input, user_data, current_field, awaiting_confirmation):
        if awaiting_confirmation:
            if self.is_positive_response(user_input):
                response = f"Excellent! Now, what's your phone number?"
                return {
                    'bot_response': response,
                    'new_state': 'collect_phone',
                    'updated_data': user_data,
                    'current_field': 'phone',
                    'awaiting_confirmation': False
                }
            elif self.is_negative_response(user_input):
                user_data['email'] = ''
                response = "Let me get your email right. Please speak it clearly like 'john at gmail dot com', or type it manually."
                return {
                    'bot_response': response,
                    'new_state': 'collect_email',
                    'updated_data': user_data,
                    'current_field': 'email',
                    'awaiting_confirmation': False,
                    'show_manual_input': True,
                    'manual_field': 'email'
                }
            else:
                response = "Is your email address correct? Please say yes or no."
                return {
                    'bot_response': response,
                    'new_state': 'collect_email',
                    'updated_data': user_data,
                    'current_field': 'email',
                    'awaiting_confirmation': True
                }
        else:
            email = self.extract_email(user_input)
            if email:
                user_data['email'] = email
                response = f"I heard your email as {email}. Is that correct?"
                return {
                    'bot_response': response,
                    'new_state': 'collect_email',
                    'updated_data': user_data,
                    'current_field': 'email',
                    'awaiting_confirmation': True
                }
            else:
                response = "I couldn't catch your email clearly. Please speak it like 'john at gmail dot com', or type it manually."
                return {
                    'bot_response': response,
                    'new_state': 'collect_email',
                    'updated_data': user_data,
                    'current_field': 'email',
                    'awaiting_confirmation': False,
                    'show_manual_input': True,
                    'manual_field': 'email'
                }
    
    def handle_phone_collection(self, user_input, user_data, current_field, awaiting_confirmation):
        if awaiting_confirmation:
            if self.is_positive_response(user_input):
                response = "Great! Which country are you from? This helps me format your number correctly."
                return {
                    'bot_response': response,
                    'new_state': 'collect_country',
                    'updated_data': user_data,
                    'current_field': 'country',
                    'awaiting_confirmation': False
                }
            elif self.is_negative_response(user_input):
                user_data['phone'] = ''
                response = "No problem! Please provide your correct phone number."
                return {
                    'bot_response': response,
                    'new_state': 'collect_phone',
                    'updated_data': user_data,
                    'current_field': 'phone',
                    'awaiting_confirmation': False,
                    'show_manual_input': True,
                    'manual_field': 'phone'
                }
            else:
                response = "Is your phone number correct? Please say yes or no."
                return {
                    'bot_response': response,
                    'new_state': 'collect_phone',
                    'updated_data': user_data,
                    'current_field': 'phone',
                    'awaiting_confirmation': True
                }
        else:
            phone = self.extract_phone(user_input)
            if phone and self.validate_phone(phone):
                user_data['phone'] = phone
                response = f"I heard your phone number as {phone}. Is that correct?"
                return {
                    'bot_response': response,
                    'new_state': 'collect_phone',
                    'updated_data': user_data,
                    'current_field': 'phone',
                    'awaiting_confirmation': True
                }
            else:
                response = "Please speak your phone number digit by digit, like 'nine eight seven six five four three two one'."
                return {
                    'bot_response': response,
                    'new_state': 'collect_phone',
                    'updated_data': user_data,
                    'current_field': 'phone',
                    'awaiting_confirmation': False,
                    'show_manual_input': True,
                    'manual_field': 'phone'
                }
    
    def handle_country_collection(self, user_input, user_data, current_field, awaiting_confirmation):
        if awaiting_confirmation:
            if self.is_positive_response(user_input):
                # Format phone with country code
                formatted_phone = self.format_phone_with_country(user_data['phone'], user_data['country'])
                user_data['phone'] = formatted_phone
                
                summary = f"Perfect! Let me confirm your details: Name: {user_data['name']}, Company: {user_data['company']}, Email: {user_data['email']}, Phone: {user_data['phone']}. Should I submit this information?"
                return {
                    'bot_response': summary,
                    'new_state': 'final_confirmation',
                    'updated_data': user_data,
                    'current_field': '',
                    'awaiting_confirmation': False
                }
            elif self.is_negative_response(user_input):
                user_data['country'] = ''
                response = "Which country are you from?"
                return {
                    'bot_response': response,
                    'new_state': 'collect_country',
                    'updated_data': user_data,
                    'current_field': 'country',
                    'awaiting_confirmation': False,
                    'show_manual_input': True,
                    'manual_field': 'country'
                }
            else:
                response = "Is your country correct? Please say yes or no."
                return {
                    'bot_response': response,
                    'new_state': 'collect_country',
                    'updated_data': user_data,
                    'current_field': 'country',
                    'awaiting_confirmation': True
                }
        else:
            country = self.extract_country(user_input)
            if country:
                user_data['country'] = country
                response = f"I heard {country}. Is that correct?"
                return {
                    'bot_response': response,
                    'new_state': 'collect_country',
                    'updated_data': user_data,
                    'current_field': 'country',
                    'awaiting_confirmation': True
                }
            else:
                response = "Could you please tell me your country name clearly?"
                return {
                    'bot_response': response,
                    'new_state': 'collect_country',
                    'updated_data': user_data,
                    'current_field': 'country',
                    'awaiting_confirmation': False,
                    'show_manual_input': True,
                    'manual_field': 'country'
                }
    
    def handle_final_confirmation(self, user_input, user_data, current_field, awaiting_confirmation):
        if self.is_positive_response(user_input):
            self.save_visitor_data(user_data)
            response = "Fantastic! Your information has been successfully submitted. Thank you for visiting Operisoft at the Community Day event. We'll be in touch soon!"
            return {
                'bot_response': response,
                'new_state': 'finished',
                'updated_data': user_data,
                'current_field': '',
                'awaiting_confirmation': False
            }
        elif self.is_negative_response(user_input):
            response = "No problem! Let's start fresh. What's your name?"
            return {
                'bot_response': response,
                'new_state': 'collect_name',
                'updated_data': self.empty_user_data.copy(),
                'current_field': 'name',
                'awaiting_confirmation': False
            }
        else:
            response = "Should I submit your information? Please say yes to submit or no to start over."
            return {
                'bot_response': response,
                'new_state': 'final_confirmation',
                'updated_data': user_data,
                'current_field': '',
                'awaiting_confirmation': False
            }
    
    def is_positive_response(self, text):
        text_lower = text.lower().strip()
        # Check exact match first for faster processing
        if text_lower in self.positive_responses:
            return True
        return any(word in text_lower for word in self.positive_responses)
    
    def is_negative_response(self, text):
        text_lower = text.lower().strip()
        # Check exact match first for faster processing
        if text_lower in self.negative_responses:
            return True
        return any(word in text_lower for word in self.negative_responses)
    
    def is_off_topic_question(self, text):
        off_topic_keywords = [
            'weather', 'time', 'date', 'news', 'sports', 'music', 'movie',
            'food', 'restaurant', 'travel', 'joke', 'story', 'game'
        ]
        return any(keyword in text.lower() for keyword in off_topic_keywords)
    
    def handle_off_topic(self, user_input, user_data):
        responses = [
            "That's interesting! But let's focus on getting your details for the AWS Community Day event. How are you today?",
            "I appreciate your question! However, I'm here to help collect your information for our event. How are you feeling today?",
            "Great question! Let's get back to our registration process. How are you doing?"
        ]
        import random
        response = random.choice(responses)
        return {
            'bot_response': response,
            'new_state': 'greeting',
            'updated_data': user_data,
            'current_field': '',
            'awaiting_confirmation': False
        }
    
    def extract_name(self, text):
        # Skip if it's a bot question
        skip_phrases = [
            "what's your name", "your name is", "what is your name",
            "tell me your name", "can you tell me", "please tell me"
        ]
        
        if any(phrase in text.lower() for phrase in skip_phrases):
            return None
        
        # Remove common phrases
        name = text.strip()
        name = re.sub(r'(my name is|i am|i\'m|call me)', '', name, flags=re.IGNORECASE).strip()
        
        # Validate name (2-50 chars, letters and spaces only)
        if len(name) < 2 or len(name) > 50 or not re.match(r'^[A-Za-z\s]+$', name):
            return None
            
        return name.title()
    
    def extract_company(self, text):
        if not text or len(text.strip()) < 2:
            return None
            
        company = text.strip()
        company = re.sub(r'(i work at|my company is|company is|i\'m from|i work for|company)', '', company, flags=re.IGNORECASE).strip()
        
        if len(company) < 2 or len(company) > 100:
            return None
            
        return company.title()
    
    def extract_email(self, text):
        if not text or len(text.strip()) < 5:
            return None
            
        text = text.lower().strip()
        
        # Enhanced speech recognition patterns
        replacements = {
            ' at the rate ': '@', ' at ': '@', ' @ ': '@', ' add ': '@',
            ' dot ': '.', ' period ': '.', ' point ': '.', ' full stop ': '.',
            ' gmail ': 'gmail', ' g mail ': 'gmail', ' jemail ': 'gmail',
            ' yahoo ': 'yahoo', ' ya who ': 'yahoo', ' yahu ': 'yahoo',
            ' hotmail ': 'hotmail', ' hot mail ': 'hotmail',
            ' outlook ': 'outlook', ' out look ': 'outlook',
            ' underscore ': '_', ' dash ': '-', ' hyphen ': '-',
            'dot com': '.com', 'dot org': '.org', 'dot net': '.net', 'dot in': '.in',
            'gmail dot com': 'gmail.com', 'yahoo dot com': 'yahoo.com',
            'hotmail dot com': 'hotmail.com', 'outlook dot com': 'outlook.com'
        }
        
        # Apply replacements efficiently
        for spoken, actual in replacements.items():
            text = text.replace(spoken, actual)
        
        # Clean up spacing
        text = re.sub(r'\s*@\s*', '@', text)
        text = re.sub(r'\s*\.\s*', '.', text)
        email_candidate = re.sub(r'\s+', '', text)
        
        # Validate email format
        email_pattern = r'^[a-zA-Z0-9][a-zA-Z0-9._-]*@[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}$'
        if re.match(email_pattern, email_candidate):
            return email_candidate.lower()
        
        # Try loose pattern matching
        email_pattern_loose = r'[a-zA-Z0-9][a-zA-Z0-9._-]*@[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}'
        matches = re.findall(email_pattern_loose, text)
        if matches:
            return matches[0].lower()
        
        return None
    
    def extract_phone(self, text):
        if not text or len(text.strip()) < 3:
            return None
            
        text = text.lower().strip()
        
        # Enhanced number word replacement for international visitors
        number_words = {
            'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
            'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
            'oh': '0', 'o': '0'
        }
        
        # Handle country code patterns
        text = re.sub(r'plus\s+', '+', text)
        text = re.sub(r'country\s+code\s+', '+', text)
        
        # Handle double/triple patterns
        text = re.sub(r'double\s+(\w+)', lambda m: number_words.get(m.group(1), m.group(1)) * 2, text)
        text = re.sub(r'triple\s+(\w+)', lambda m: number_words.get(m.group(1), m.group(1)) * 3, text)
        
        # Replace number words
        for word, digit in number_words.items():
            text = text.replace(word, digit)
        
        # Clean and extract digits with plus sign
        text = re.sub(r'(\d)\s+(\d)', r'\1\2', text)
        phone_chars = re.sub(r'[^\d\+]', '', text)
        
        # Handle international format
        if phone_chars.startswith('+'):
            digits_part = phone_chars[1:]
            if len(digits_part) >= 8 and len(digits_part) <= 15:
                return phone_chars
        elif len(phone_chars) >= 8 and len(phone_chars) <= 15:
            return phone_chars
            
        return None
    
    def validate_phone(self, phone):
        if not phone:
            return False
        # Enhanced validation for international numbers
        if phone.startswith('+'):
            digits_part = phone[1:]
            return len(digits_part) >= 8 and len(digits_part) <= 15 and digits_part.isdigit()
        return len(phone) >= 8 and len(phone) <= 15 and phone.isdigit()
    
    def extract_country(self, text):
        if not text or len(text.strip()) < 2:
            return None
            
        country = text.strip().lower()
        country = re.sub(r'(i am from|i\'m from|from|country is|my country)', '', country, flags=re.IGNORECASE).strip()
        
        if len(country) < 2 or len(country) > 50:
            return None
            
        return country.title()
    
    def format_phone_with_country(self, phone, country):
        if not phone or not country:
            return phone
            
        # If phone already has country code, return as is
        if phone.startswith('+'):
            return phone
            
        country_lower = country.lower()
        country_code = self.country_codes.get(country_lower, '')
        
        if country_code:
            return f"{country_code}{phone}"
        else:
            return phone
    
    def save_visitor_data(self, user_data):
        try:
            user_data['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            user_data['event'] = 'Community Day'
            
            df_new = pd.DataFrame([user_data])
            
            if os.path.exists(EXCEL_FILE):
                try:
                    df_existing = pd.read_excel(EXCEL_FILE)
                    df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                except (pd.errors.EmptyDataError, pd.errors.ExcelFileError) as e:
                    logger.warning(f"Excel file error, creating new: {e}")
                    df_combined = df_new
            else:
                df_combined = df_new
            
            df_combined.to_excel(EXCEL_FILE, index=False)
            logger.info(f"Visitor data saved: {user_data['name']} - {user_data['company']}")
            
        except Exception as e:
            logger.error(f"Error saving visitor data: {e}")

bot_manager = VoiceBotManager()

@app.route('/process_conversation', methods=['POST'])
def process_conversation():
    # Initialize default values
    state = 'greeting'
    user_data = {}
    current_field = ''
    awaiting_confirmation = False
    
    try:
        data = request.json
        user_input = data.get('user_input', '')
        state = data.get('conversation_state', 'greeting')
        user_data = data.get('user_data', {})
        current_field = data.get('current_field', '')
        awaiting_confirmation = data.get('awaiting_confirmation', False)
        
        result = bot_manager.process_conversation(
            user_input, state, user_data, current_field, awaiting_confirmation
        )
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error in conversation processing: {e}")
        return jsonify({
            'bot_response': 'I apologize, there was an error. Could you please repeat that?',
            'new_state': state,
            'updated_data': user_data,
            'current_field': current_field,
            'awaiting_confirmation': False
        })

@app.route('/manual_input', methods=['POST'])
def handle_manual_input():
    try:
        data = request.json
        field = data.get('field', '')
        value = data.get('value', '')
        user_data = data.get('user_data', {})
        
        if field and value.strip():
            user_data[field] = value.strip()
            
            # Determine next field
            field_order = ['name', 'company', 'email', 'phone', 'country']
            current_index = field_order.index(field)
            
            if current_index < len(field_order) - 1:
                next_field = field_order[current_index + 1]
                response = f"Thank you! Now, what's your {next_field}?"
                new_state = f'collect_{next_field}'
            else:
                summary = f"Perfect! Let me confirm: Name: {user_data['name']}, Company: {user_data['company']}, Email: {user_data['email']}, Phone: {user_data['phone']}. Should I submit this?"
                response = summary
                new_state = 'final_confirmation'
                next_field = ''
            
            return jsonify({
                'bot_response': response,
                'new_state': new_state,
                'updated_data': user_data,
                'current_field': next_field,
                'awaiting_confirmation': False
            })
        else:
            return jsonify({
                'bot_response': f'Please enter a valid {field}.',
                'new_state': f'collect_{field}',
                'updated_data': user_data,
                'current_field': field,
                'awaiting_confirmation': False
            })
            
    except Exception as e:
        logger.error(f"Error in manual input: {e}")
        return jsonify({'error': 'Failed to process manual input'}), 500

@app.route('/chat', methods=['POST'])
def handle_chat():
    try:
        data = request.json
        text = data.get('text', '')
        voice = data.get('voice', 'Matthew')
        
        if not polly_client:
            return jsonify({'error': 'Text-to-speech service unavailable'}), 503
        
        # Direct Polly synthesis for faster response
        response = polly_client.synthesize_speech(
            Text=text,
            OutputFormat='mp3',
            VoiceId=voice,
            Engine='neural'
        )
        
        audio_bytes = response['AudioStream'].read()
        audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
        
        return jsonify({
            'audio_base64': audio_base64
        })
        
    except Exception as e:
        logger.error(f"Error in text-to-speech: {e}")
        return jsonify({'error': str(e)}), 500

# Removed Bedrock enhancement for faster processing

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    host = os.getenv('FLASK_HOST', '127.0.0.1')
    port = int(os.getenv('FLASK_PORT', 5000))
    app.run(debug=debug_mode, host=host, port=port)