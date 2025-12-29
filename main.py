import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import sqlite3
from datetime import datetime
import asyncio
import json
import base64
import re
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
import time
from gmail_helper import get_latest_pokernow_code
import openai
from collections import defaultdict
from db_helper import setup_database, get_user_profile, add_user_profile, update_user_profile, add_game_record, update_game_status, add_player_to_game, determine_payment_instructions, remove_player_from_game

# Load environment variables
load_dotenv()

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True
intents.dm_messages = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Global variables
active_games = {}  # Store active game information
pending_players = {}  # Store players waiting to be verified
current_game_url = None

# Store conversation history per user (user_id: [messages])
user_histories = defaultdict(list)

# Track join requests per user (user_id: amount)
pending_joins = {}

# Map table names to join amounts
table_name_to_amount = {}

# --- PokerNow Selenium Automation ---

def setup_selenium():
    chrome_options = Options()
    #chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chromedriver_path = "/Users/andrewli/Documents/host_bot/drivers/chromedriver"
    service = Service(chromedriver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

async def create_pokernow_game():
    """Create a new PokerNow game and return the URL"""
    driver = setup_selenium()
    try:
        # Log into PokerNow
        if os.path.exists("pokernow_cookies.pkl"):
            driver.get('https://www.pokernow.club/')
            with open("pokernow_cookies.pkl", "rb") as f:
                cookies = pickle.load(f)
            for cookie in cookies:
                driver.add_cookie(cookie)
            driver.refresh()
        else:
            driver.get('https://www.pokernow.club/')
            login_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "a.button-2.mini.green"))
            )
            login_button.click()
            pokernow_email = os.getenv('POKERNOW_EMAIL')
            email_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email']"))
            )        
            email_input.clear()
            email_input.send_keys(pokernow_email)
            send_code_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='submit'][value='Send me the Login Code']"))
            )
            send_code_button.click()
            code_input = WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text']"))
            )
            time.sleep(5)
            pokernow_code = get_latest_pokernow_code()
            if pokernow_code:
                code_input.clear()
                code_input.send_keys(pokernow_code)
                submit_btn = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='submit']"))
                )
                submit_btn.click()
            else:
                print("Could not find PokerNow login code in Gmail.")
        # --- End Gmail code retrieval ---

        # Click create game button
        create_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "a#new-game-button"))
        )
        create_button.click()
        
        # Wait for the player name input to appear and type 'HOST'
        player_name_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder='Your Nickname']"))
        )
        player_name_input.clear()
        player_name_input.send_keys("HOST\n")

        # Set stack to 1
        stack_input = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder='Your Stack']"))
        )
        stack_input.clear()
        stack_input.send_keys("1")

        # Click the "Sit with Away set" checkbox
        away_checkbox = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input#sit-as-away[type='checkbox']"))
        )
        away_checkbox.click()

        # Click the "Take the Seat" button
        take_the_seat_button = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.button-1.med-button.highlighted.green[type='submit']"))
        )
        take_the_seat_button.click()

        # Change the game settings
        options_button = WebDriverWait(driver, 60).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.top-buttons-button.options"))
        )
        options_button.click()

        game_config_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.button-1.gray.configs"))
        )
        game_config_button.click()
        
        # Use cents values
        use_cents_section = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//div[contains(., 'Use cents values?') and contains(@class, 'form-1-input-control')]"))
        )
        use_cents_button = use_cents_section.find_element(By.XPATH, ".//button[contains(., 'Yes')]")
        driver.execute_script("arguments[0].scrollIntoView(true);", use_cents_button)
        use_cents_button.click()

        # Allow Run it Twice? Ask Players
        rit_section = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//div[contains(., 'Allow Run it Twice?') and contains(@class, 'form-1-input-control')]"))
        )
        rit_button = rit_section.find_element(By.XPATH, ".//button[contains(., 'Ask Players')]")
        driver.execute_script("arguments[0].scrollIntoView(true);", rit_button)
        rit_button.click()

        # Allow UTG Straddle 2BB? Yes
        str_section = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//div[contains(., 'Allow UTG Straddle 2BB?') and contains(@class, 'form-1-input-control')]"))
        )
        str_button = str_section.find_element(By.XPATH, ".//button[contains(., 'Yes')]")
        driver.execute_script("arguments[0].scrollIntoView(true);", str_button)
        str_button.click()

        # Showdown Presentation Time: Fast (3s)
        showdown_section = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//div[contains(., 'Showdown Presentation Time') and contains(@class, 'form-1-input-control')]"))
        )
        showdown_button = showdown_section.find_element(By.XPATH, ".//button[contains(., 'Fast (3s)')]")
        driver.execute_script("arguments[0].scrollIntoView(true);", showdown_button)
        showdown_button.click()

        # Decision Time Limit (seconds): 12
        decision_time_section = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//label[contains(text(), 'Decision Time Limit (seconds)')]/.."))
        )
        decision_time_input = decision_time_section.find_element(By.TAG_NAME, "input")
        driver.execute_script("arguments[0].scrollIntoView(true);", decision_time_input)
        decision_time_input.clear()
        decision_time_input.send_keys("12")

        # Time Bank Length (seconds): 45
        time_bank_section = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//label[contains(text(), 'Time Bank Length (seconds)')]/.."))
        )
        time_bank_input = time_bank_section.find_element(By.TAG_NAME, "input")
        driver.execute_script("arguments[0].scrollIntoView(true);", time_bank_input)
        time_bank_input.clear()
        time_bank_input.send_keys("45")

        # Number of played hands to fill time bank: 30
        refill_hands_section = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//label[contains(text(), 'Number of played hands to fill time bank')]/.."))
        )
        refill_hands_input = refill_hands_section.find_element(By.TAG_NAME, "input")
        driver.execute_script("arguments[0].scrollIntoView(true);", refill_hands_input)
        refill_hands_input.clear()
        refill_hands_input.send_keys("30")

        # SB: 0.25
        sb_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder='SB']"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", sb_input)
        sb_input.clear()
        sb_input.send_keys("0.25")

        # BB: 0.50
        bb_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder='BB']"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", bb_input)
        bb_input.clear()
        bb_input.send_keys("0.50")

        # Click UPDATE
        update_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.button-1.green[type='submit']"))
        )
        update_button.click()

        # Wait for the "Game successfully updated." popup to appear
        success_popup = WebDriverWait(driver, 20).until(
            EC.visibility_of_element_located((By.XPATH, "//div[contains(text(), 'Game successfully updated.')]"))
        )
        ok_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Ok']"))
        )
        ok_button.click()

        game_url = driver.current_url
        with open("pokernow_cookies.pkl", "wb") as f:
            pickle.dump(driver.get_cookies(), f)
        return game_url
    finally:
        driver.quit()

async def manage_pokernow_game(table_name, user_id=None, user_name=None):
    chrome_options = Options()
    # chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chromedriver_path = "/Users/andrewli/Documents/host_bot/drivers/chromedriver"
    service = Service(chromedriver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    try:
        driver.get(current_game_url)
        # Load cookies
        try:
            with open("pokernow_cookies.pkl", "rb") as f:
                cookies = pickle.load(f)
            for cookie in cookies:
                driver.add_cookie(cookie)
            driver.refresh()
        except Exception as e:
            return f"Error: Could not load cookies: {e}"
        
        # Wait for the page to load and perform actions
        options_button = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.top-buttons-button.options"))
        )
        options_button.click()
        players_button = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.button-1.gray.players"))
        )
        players_button.click()
        player_rows = driver.find_elements(By.CSS_SELECTOR, "div.config-player-row.request-game-ingress")
        found = False
        for row in player_rows:
            try:
                name_elem = row.find_element(By.CSS_SELECTOR, "p.name")
                pokernow_table_name = name_elem.text.strip()
                pokernow_table_name = re.sub(r' ID: [A-Za-z0-9]{10}$', '', pokernow_table_name).strip()
                
                if pokernow_table_name.strip().lower() == table_name.strip().lower():
                    found = True
                    approve_button = row.find_element(By.CSS_SELECTOR, "button.button-1.config-action-button.green")
                    approve_button.click()
                    try:
                        stack_input = WebDriverWait(driver, 15).until(
                            lambda d: d.find_element(By.CSS_SELECTOR, "input[placeholder='Stack']")
                        )
                        actual_stack = float(stack_input.get_attribute('value'))
                        expected_stack = table_name_to_amount.get(table_name)
                        
                        if expected_stack is not None:
                            if abs(actual_stack - expected_stack) <= 0.01:
                                print(f"Stack amounts match, looking for Approve Player button...")
                                
                                modal_approve_button = WebDriverWait(driver, 10).until(
                                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Approve Player')]"))
                                )
                                print(f"Clicking Approve Player button for {table_name}")
                                modal_approve_button.click()
                                time.sleep(1)
                                
                                success_msg = f"You will now be added to the game as '{table_name}' with a stack of ${actual_stack:.2f}. Good luck!"
                                
                                # Add player to database
                                add_player_to_game(user_id, user_name, table_name, expected_stack, current_game_url)
                                
                                return success_msg
                            else:
                                warning_msg = f"WARNING: Requested stack for '{table_name}' does not match join amount. Expected amount: {expected_stack}, Requested amount: {actual_stack}"
                                return warning_msg
                    except Exception as e:
                        error_msg = f"Error checking stack amount: {e}"
                        return error_msg
            except Exception as e:
                error_msg = f"Error processing row: {e}"
                return error_msg
        if not found:
            not_found_msg = f"Player name '{table_name}' not found in the PokerNow waiting list."
            return not_found_msg
        time.sleep(0.5)
    finally:
        driver.quit()
    
    return "Unknown error occurred"

async def remove_player(table_name, game_url):
    """
    Remove a player from the PokerNow game and return their buyout amount
    
    Args:
        table_name (str): Player's table name in PokerNow
        game_url (str): Current game URL
    
    Returns:
        float: Buyout amount, or None if not found
    """
    print(f"[DEBUG] remove_player called with table_name='{table_name}', game_url='{game_url}'")
    
    chrome_options = Options()
    # chrome_options.add_argument('--headless')  # Run in headless mode for this check
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chromedriver_path = "/Users/andrewli/Documents/host_bot/drivers/chromedriver"
    service = Service(chromedriver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    try:
        print(f"[DEBUG] Navigating to game URL: {game_url}")
        driver.get(game_url)

        # Load cookies
        try:
            with open("pokernow_cookies.pkl", "rb") as f:
                cookies = pickle.load(f)
            for cookie in cookies:
                driver.add_cookie(cookie)
            driver.refresh()
        except Exception as e:
            return f"Error: Could not load cookies: {e}"
        
        # Wait for the page to load and perform actions
        print("[DEBUG] Looking for options button...")
        options_button = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.top-buttons-button.options"))
        )
        options_button.click()
        time.sleep(0.5)
        print("[DEBUG] Clicked options button")

        print("[DEBUG] Looking for players button...")
        players_button = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.button-1.gray.players"))
        )
        players_button.click()
        time.sleep(0.5)
        print("[DEBUG] Clicked players button")

        player_rows = driver.find_elements(By.CSS_SELECTOR, "div.config-player-row")
        print(f"[DEBUG] Found {len(player_rows)} player rows")
                
        for i, row in enumerate(player_rows):
            print(f"[DEBUG] Processing player row {i+1}/{len(player_rows)}")
            try:
                # Find the name element within this specific row
                name_elem = row.find_element(By.CSS_SELECTOR, "p.name")
                pokernow_table_name = name_elem.text.strip()
                pokernow_table_name = re.sub(r' ID: [A-Za-z0-9]{10}$', '', pokernow_table_name).strip()
                print(f"[DEBUG] Player name found: '{pokernow_table_name}', looking for: '{table_name}'")
                
                if pokernow_table_name.strip().lower() == table_name.strip().lower():
                    print(f"[DEBUG] MATCH FOUND! Player {table_name} matches")
                    
                    # Find the player's current stack amount from the main screen BEFORE clicking Edit
                    print("[DEBUG] Looking for stack amount element within the row...")
                    
                    # Find the stack amount within this specific row using the HTML structure from the image
                    try:
                        # Look for the stack amount in the status section: <span class="normal-value">0.11</span>
                        stack_elem = row.find_element(By.CSS_SELECTOR, "span.normal-value")
                        stack_text = stack_elem.text.strip()
                        print(f"[DEBUG] Found stack text: '{stack_text}' from main screen")
                        
                        if not stack_text:
                            print(f"[DEBUG] Stack text is empty, trying alternative method...")
                            # Try getting from parent span if direct text is empty
                            parent_span = stack_elem.find_element(By.XPATH, "./..")
                            stack_text = parent_span.text.strip()
                            print(f"[DEBUG] Parent span text: '{stack_text}'")
                        
                        # Extract numeric value from the stack text
                        numeric_value_match = re.search(r'(\d+\.?\d*)', stack_text)
                        if numeric_value_match:
                            buyout_amount = float(numeric_value_match.group(1))
                            print(f"[DEBUG] Extracted buyout amount from main screen: {buyout_amount}")
                        else:
                            print(f"[DEBUG] No numeric value found in stack text '{stack_text}', setting to 0.0")
                            buyout_amount = 0.0
                            
                    except Exception as e:
                        print(f"[DEBUG] Error finding stack amount from main screen: {e}")
                        print(f"[DEBUG] Setting buyout amount to 0.0")
                        buyout_amount = 0.0
                    
                    # Now click the EDIT button
                    print(f"[DEBUG] Found player {table_name}, attempting to click EDIT button...")
                    edit_button = row.find_element(By.CSS_SELECTOR, "button.button-1.config-action-button")
                    print(f"[DEBUG] Clicking EDIT button for player {table_name} using JavaScript...")
                    driver.execute_script("arguments[0].click();", edit_button)

                    # Wait for the edit dialog to open
                    time.sleep(1)
                    
                    print("[DEBUG] Looking for Remove Player button...")
                    # Now find and click the remove button (usually red or has "Remove" text)
                    # Find the button with "Remove Player" text
                    try:
                        remove_button = WebDriverWait(driver, 15).until(
                            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Remove Player')]"))
                        )
                        print(f"[DEBUG] Found Remove Player button, clicking...")
                        remove_button.click()
                        time.sleep(0.5)
                        
                        print("[DEBUG] Looking for confirm button...")
                        # Click the confirm button in the popup
                        confirm_button = WebDriverWait(driver, 15).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.button-1.middle-gray"))
                        )
                        print(f"[DEBUG] Found confirm button, clicking...")
                        confirm_button.click()
                        time.sleep(0.5)
                        
                        print(f"[DEBUG] Successfully removed player {table_name} with buyout amount {buyout_amount}")
                        return buyout_amount
                        
                    except Exception as e:
                        print(f"[DEBUG] Error with remove/confirm buttons: {e}")
                        return None
                    
                # If we get here, we didn't find the player, so break to avoid stale element issues
                if i == len(player_rows) - 1:
                    print(f"[DEBUG] Player {table_name} not found in any row")
                    return None
                    
            except Exception as e:
                print(f"Error processing player row: {e}")
                continue
        
        return None  # Player not found
        
    except Exception as e:
        print(f"Error getting buyout amount: {e}")
        return None
    finally:
        driver.quit()

# --- Discord Slash Commands ---

GUILD_ID = discord.Object(id=1383626042132009011)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    setup_database()

    try:
        # Replace GUILD_ID with your server's ID for instant sync
        #bot.tree.clear_commands(guild=None)
        #await bot.tree.sync()

        await bot.tree.sync(guild=GUILD_ID)
        print("Synced slash commands to guild!")
    except Exception as e:
        print(f"Error syncing commands: {e}")

@bot.tree.command(name="poll", description="Create a poll for a poker game", guild=GUILD_ID)
async def poll_command(interaction: discord.Interaction):
    if interaction.user.id != int(os.getenv("ADMIN_DISCORD_ID")):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    poll_message = await interaction.channel.send(
        "**50nl Interest?**\n"
        "React with 👍 if you're interested in playing.\n"
        "Game up with 7 reactions."
    )
    await poll_message.add_reaction('👍')
    active_games[poll_message.id] = {
        'message': poll_message,
        'channel': interaction.channel,
        'status': 'polling',
        'start_time': datetime.now()
    }
    await interaction.response.send_message("Poll created!", ephemeral=True)

@bot.tree.command(name="endgame", description="End the current game and process final payments", guild=GUILD_ID)
async def endgame_command(interaction: discord.Interaction):
    global current_game_url  # Add this line
    
    if interaction.user.id != 173861281315553280:
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    if current_game_url is None:
        await interaction.response.send_message("❌ There is no active game to end.", ephemeral=True)
        return
    
    # Update game status in database
    update_game_status(current_game_url, "ended", datetime.now())
    
    # Clear current game
    current_game_url = None
    
    await interaction.response.send_message("Game ended and final payments processed.")

@bot.tree.command(name="join", description="Request to join the game", guild=GUILD_ID)
@app_commands.describe(amount="Buy-in amount (e.g. 50). Use 0 to confirm after sending payment.")
async def join_command(interaction: discord.Interaction, amount: float):
    if current_game_url is None:
        await interaction.response.send_message("❌ There is no active game to join.")
        return
    
    user_id = str(interaction.user.id)
    
    add_user_profile(user_id, interaction.user.name)
    profile = get_user_profile(user_id)
    if profile:
        venmo = profile[4]
        cashapp = profile[5]
        zelle = profile[6]
        table_name = profile[7]
        if not (venmo or cashapp or zelle):
            await interaction.response.send_message(
                "You must set at least one payment method before joining a game. "
                "Use the `/set-methods` command to add your Venmo, CashApp, or Zelle information.",
                ephemeral=True
            )
            return
        if not table_name:
            await interaction.response.send_message(
                "You must set your PokerNow table name before joining a game. Make sure it is copied and pasted exactly as it appears in PokerNow. \n\n"
                "Use the `/set-pnow-name` command to add your PokerNow table name.",
                ephemeral=True
            )
            return
    
    if amount == 0:
        if user_id not in pending_joins:
            await interaction.response.send_message(
                "You must first use `/join amount:{amount}` before confirming. Example: `/join amount:50`"
            )
            return
        
        # Defer the response immediately to prevent timeout
        await interaction.response.defer(thinking=True)
        
        join_amount = pending_joins.get(user_id)
        if join_amount is not None:
            table_name_to_amount[table_name] = join_amount
        
        # Run the PokerNow automation and get the result message
        result_message = await manage_pokernow_game(table_name, user_id=user_id, user_name=interaction.user.name)
        del pending_joins[user_id]
        
        # Ensure the message is a single string and send it
        if isinstance(result_message, str):
            await interaction.followup.send(result_message)
        else:
            await interaction.followup.send(str(result_message))
        
        return
    
    # Determine payment instructions
    payment_info = determine_payment_instructions(user_id, amount, current_game_url)
    
    pending_joins[user_id] = amount
    await interaction.response.send_message(
        f"You have requested to join the game for ${amount:.2f}.\n\n"
        f"{payment_info['message']}\n\n"
        f"**REMEMBER: PLEASE NO POKER IN DESCRIPTION. I WILL TAKE YOUR BUYIN IF I SEE IT**\n\n"
        f"# After you have requested a seat, use `/join amount:0` to be let into the game."
    )

@bot.tree.command(name="call", description="Request to leave the game in X minutes", guild=GUILD_ID)
@app_commands.describe(minutes="Minutes until you want to leave (default 15)")
async def call_command(interaction: discord.Interaction, minutes: int = 15):
    if current_game_url is None:
        await interaction.response.send_message("❌ There is no active game to leave.")
        return
    await interaction.response.send_message(
        f"You have requested to leave the game in {minutes} minutes."
    )

@bot.tree.command(name="add", description="Request to add to your stack", guild=GUILD_ID)
@app_commands.describe(amount="Amount to add to your stack")
async def add_command(interaction: discord.Interaction, amount: float):
    if current_game_url is None:
        await interaction.response.send_message("❌ There is no active game to add chips to.")
        return
    
    user_id = str(interaction.user.id)
    
    # Check if player is in the current game
    conn = sqlite3.connect('poker_games.db')
    c = conn.cursor()
    c.execute('''
        SELECT discord_id FROM players 
        WHERE game_url = ? AND discord_id = ? AND playing = 1
    ''', (current_game_url, user_id))
    player_in_game = c.fetchone()
    conn.close()
    
    if not player_in_game:
        await interaction.response.send_message("❌ You must be in the current game to add chips. Use `/join` to join the game first.")
        return
    
    # Determine payment instructions using the same logic as join
    payment_info = determine_payment_instructions(user_id, amount, current_game_url)
    
    await interaction.response.send_message(
        f"You have requested to add ${amount:.2f} to your stack.\n\n"
        f"{payment_info['message']}\n\n"
        f"Please send the additional funds and wait for confirmation."
    )

@bot.tree.command(name="join-cancel", description="Cancel your pending join request", guild=GUILD_ID)
async def cancel_join_command(interaction: discord.Interaction):
    if current_game_url is None:
        await interaction.response.send_message("❌ There is no active game to cancel joining.")
        return
    
    user_id = str(interaction.user.id)
    
    # Check if player has a pending join request in the pending_joins object
    if user_id not in pending_joins:
        await interaction.response.send_message("❌ You don't have a pending join request to cancel.")
        return
    
    # Remove the pending join request from the pending_joins object
    del pending_joins[user_id]
    
    await interaction.response.send_message("✅ Your join request has been cancelled.")

@bot.tree.command(name="set-methods", description="Set your payment method information", guild=GUILD_ID)
@app_commands.describe(
    payment_type="Type: venmo, cashapp, or zelle",
    handle="Your handle (e.g. @venmo, $cashapp, or 10-digit phone for zelle)"
)
async def set_command(interaction: discord.Interaction, payment_type: str, handle: str):
    user_id = str(interaction.user.id)
    payment_type = payment_type.lower()
    handle = handle.lower()
    if payment_type == 'venmo':
        if not handle.startswith('@'):
            handle = '@' + handle
        update_user_profile(user_id, venmo=handle)
        await interaction.response.send_message(f"Your Venmo handle has been set to {handle}", ephemeral=True)
    elif payment_type == 'cashapp':
        if not handle.startswith('$'):
            handle = '$' + handle
        update_user_profile(user_id, cashapp=handle)
        await interaction.response.send_message(f"Your Cash App handle has been set to {handle}", ephemeral=True)
    elif payment_type == 'zelle':
        digits = ''.join(filter(str.isdigit, handle))
        if len(digits) != 10:
            await interaction.response.send_message(
                "Zelle number should be a 10-digit phone number, e.g. 1234567890, 123-456-7890, or (123)456-7890",
                ephemeral=True
            )
            return
        update_user_profile(user_id, zelle=digits)
        await interaction.response.send_message(f"Your Zelle phone number has been set to {digits}", ephemeral=True)
    else:
        await interaction.response.send_message(
            "Invalid payment type. Use one of: venmo, cashapp, zelle.",
            ephemeral=True
        )

@bot.tree.command(name="set-pnow-name", description="Set your PokerNow table name", guild=GUILD_ID)
@app_commands.describe(table_name="Your PokerNow table name (case sensitive, copy-paste from PokerNow)")
async def set_pnow_name_command(interaction: discord.Interaction, table_name: str):
    user_id = str(interaction.user.id)
    update_user_profile(user_id, table_name=table_name)
    await interaction.response.send_message(
        f"Your PokerNow table name has been set to `{table_name}`."
    )

@bot.tree.command(name="leave", description="Leave the current game", guild=GUILD_ID)
async def leave_command(interaction: discord.Interaction):
    if current_game_url is None:
        await interaction.response.send_message("❌ There is no active game to leave.")
        return
    
    user_id = str(interaction.user.id)
    
    # Check if player is in the current game
    conn = sqlite3.connect('poker_games.db')
    c = conn.cursor()
    c.execute('''
        SELECT table_name, playing 
        FROM players 
        WHERE game_url = ? AND discord_id = ? AND playing = 1
    ''', (current_game_url, user_id))
    
    result = c.fetchone()
    if not result:
        await interaction.response.send_message("❌ You are not currently in the game.")
        return
    
    table_name, playing = result
    
    # Defer response since we need to check PokerNow
    await interaction.response.defer(thinking=True)
    
    # Get buyout amount from PokerNow
    buyout_amount = await remove_player(table_name, current_game_url)
    
    if buyout_amount is None:
        await interaction.followup.send("❌ Could not retrieve your buyout amount from PokerNow. Please try again.")
        return
    
    # Update database
    success = remove_player_from_game(user_id, current_game_url, buyout_amount)
    if success:
        await interaction.followup.send(f"✅ You have left the game. Your buyout amount was ${buyout_amount:.2f}.")
    else:
        await interaction.response.send_message(
            "❌ You are not currently in the active game."
        )

# --- DM Handler for Table Name after Join Confirm and OpenAI Chat ---

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Process commands first (slash commands)
    await bot.process_commands(message)

    # Only handle DMs for table name and OpenAI chat
    if isinstance(message.channel, discord.DMChannel):
        global current_game_url
        if current_game_url is None:
            return
        user_id = str(message.author.id)
        user_message = message.content



        # Fallback: OpenAI chat for DMs
        system_prompt = {
            "role": "system",
            "content": (
                "You are a helpful, professional poker game host bot. "
                "You help players join games and provide payment instructions. "
                f"The link to your game is: "
                f"{'[Click here to join the game](' + current_game_url + ')' if current_game_url else 'No game is currently active.'} "
                "Always be friendly, clear, and concise."
            )
        }
        history = [system_prompt] + user_histories[user_id] + [{"role": "user", "content": user_message}]
        try:
            response = openai.chat.completions.create(
                model="gpt-4.1-nano-2025-04-14",
                messages=history,
                max_tokens=256,
                temperature=0.7,
            )
            assistant_reply = response.choices[0].message.content
        except Exception as e:
            assistant_reply = "Sorry, there was an error contacting the AI."
        user_histories[user_id].append({"role": "user", "content": user_message})
        user_histories[user_id].append({"role": "assistant", "content": assistant_reply})
        await message.channel.send(assistant_reply)

@bot.event
async def on_reaction_add(reaction, user):
    """Handle reactions to the poll message"""
    if user.bot:
        return

    message = reaction.message
    if message.id in active_games and str(reaction.emoji) == '👍':
        # Count only unique users who reacted with 👍
        users = [u async for u in reaction.users() if not u.bot]
        reaction_count = len(users)

        if reaction_count >= 1 and active_games[message.id]['status'] == 'polling':
            active_games[message.id]['status'] = 'creating'
            # Create PokerNow game
            global current_game_url
            game_url = await create_pokernow_game()
            current_game_url = game_url

            # Store game information
            active_games[message.id]['poker_now_url'] = game_url
            active_games[message.id]['status'] = 'active'

            # Add to database
            add_game_record(game_url, "active")

            # Send game information
            await message.channel.send(
                f"**0.25/0.50 NLHE: {game_url}**\n\n"
                f"DM ME AFTER REQUESTING A SEAT\n"
                f"CONFIRM WITH ME BEFORE SENDING ANY PAYMENT\n"
                f"I am a bot, so please be patient with me :)\n"
            )

def main():
    bot.run(os.getenv('DISCORD_TOKEN'))

if __name__ == "__main__":
    main()
