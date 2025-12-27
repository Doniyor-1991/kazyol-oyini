from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import random
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kazyol_secret_key_2024'
socketio = SocketIO(app, cors_allowed_origins="*")

games = {}

CARD_VALUES = {
    '6': 0, '7': 0, '8': 0, '9': 0,
    '10': 10, 'J': 2, 'Q': 3, 'K': 4, 'A': 11
}

SUITS = ['♠', '♥', '♦', '♣']
RANKS = ['6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']

def create_deck():
    return [{'rank': rank, 'suit': suit} for suit in SUITS for rank in RANKS]

def deal_cards(deck):
    random.shuffle(deck)
    hands = [deck[i:i+4] for i in range(0, 24, 4)]
    trump_card = deck[24]
    return hands, trump_card

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('create_game')
def create_game(data):
    game_id = str(uuid.uuid4())[:8]
    player_name = data['name']
    
    games[game_id] = {
        'players': [{'id': request.sid, 'name': player_name, 'team': None}],
        'creator': request.sid,
        'state': 'waiting',
        'deck': create_deck(),
        'hands': [],
        'trump': None,
        'current_trick': [],
        'current_player': 0,
        'scores': {'team1': 0, 'team2': 0},
        'round_scores': {'team1': 0, 'team2': 0},
        'tricks_won': {'team1': 0, 'team2': 0}
    }
    
    join_room(game_id)
    emit('game_created', {
        'game_id': game_id, 
        'player_name': player_name,
        'is_creator': True
    })

@socketio.on('join_game')
def join_game(data):
    game_id = data['game_id']
    player_name = data['name']
    
    if game_id not in games:
        emit('error', {'message': "Bunday o'yin topilmadi!"})
        return
    
    game = games[game_id]
    
    if len(game['players']) >= 6:
        emit('error', {'message': "O'yin to'lgan!"})
        return
    
    if game['state'] != 'waiting':
        emit('error', {'message': "O'yin allaqachon boshlangan!"})
        return
    
    team = 'team1' if len(game['players']) % 2 == 0 else 'team2'
    
    game['players'].append({
        'id': request.sid,
        'name': player_name,
        'team': team
    })
    
    join_room(game_id)
    
    emit('player_joined', {
        'players': game['players'],
        'your_team': team,
        'is_creator': False
    }, room=game_id)

@socketio.on('start_game')
def start_game_request(data):
    game_id = data['game_id']
    
    if game_id not in games:
        emit('error', {'message': "O'yin topilmadi!"})
        return
    
    game = games[game_id]
    
    if len(game['players']) < 2:
        emit('error', {'message': "Kamida 2 kishi kerak!"})
        return
    
    if len(game['players']) % 2 != 0:
        emit('error', {'message': "Juft son o'yinchi kerak (2, 4 yoki 6)!"})
        return
    
    start_game(game_id)

def start_game(game_id):
    game = games[game_id]
    
    hands, trump = deal_cards(game['deck'])
    game['hands'] = hands
    game['trump'] = trump
    game['state'] = 'playing'
    game['current_player'] = 0
    game['current_trick'] = []
    game['round_scores'] = {'team1': 0, 'team2': 0}
    
    for i, player in enumerate(game['players']):
        socketio.emit('game_started', {
            'your_cards': hands[i],
            'trump': trump,
            'current_player': 0,
            'players': game['players']
        }, room=player['id'])

@socketio.on('play_card')
def play_card(data):
    game_id = data['game_id']
    card = data['card']
    
    if game_id not in games:
        return
    
    game = games[game_id]
    player_index = next((i for i, p in enumerate(game['players']) if p['id'] == request.sid), None)
    
    if player_index is None or player_index != game['current_player']:
        emit('error', {'message': "Sizning navbatingiz emas!"})
        return
    
    if not is_valid_move(game, player_index, card):
        emit('error', {'message': "Bu kartani tashlay olmaysiz!"})
        return
    
    game['hands'][player_index].remove(card)
    game['current_trick'].append({'player': player_index, 'card': card})
    
    game['current_player'] = (game['current_player'] + 1) % len(game['players'])
    
    if len(game['current_trick']) == len(game['players']):
        winner = determine_trick_winner(game)
        team = game['players'][winner]['team']
        
        trick_points = sum(CARD_VALUES[c['card']['rank']] for c in game['current_trick'])
        game['round_scores'][team] += trick_points
        game['tricks_won'][team] += 1
        
        game['current_trick'] = []
        game['current_player'] = winner
        
        if all(len(hand) == 0 for hand in game['hands']):
            end_round(game_id)
            return
    
    emit('game_update', {
        'current_trick': game['current_trick'],
        'current_player': game['current_player'],
        'round_scores': game['round_scores'],
        'tricks_won': game['tricks_won']
    }, room=game_id)
    
    for i, player in enumerate(game['players']):
        socketio.emit('update_hand', {
            'your_cards': game['hands'][i]
        }, room=player['id'])

def is_valid_move(game, player_index, card):
    if len(game['current_trick']) == 0:
        return True
    
    lead_suit = game['current_trick'][0]['card']['suit']
    player_hand = game['hands'][player_index]
    
    has_suit = any(c['suit'] == lead_suit for c in player_hand)
    
    if has_suit and card['suit'] != lead_suit:
        return False
    
    return True

def determine_trick_winner(game):
    trump_suit = game['trump']['suit']
    lead_suit = game['current_trick'][0]['card']['suit']
    
    best_card = None
    winner = None
    
    for trick_card in game['current_trick']:
        card = trick_card['card']
        player = trick_card['player']
        
        if best_card is None:
            best_card = card
            winner = player
            continue
        
        if card['suit'] == trump_suit:
            if best_card['suit'] != trump_suit or RANKS.index(card['rank']) > RANKS.index(best_card['rank']):
                best_card = card
                winner = player
        elif card['suit'] == lead_suit and best_card['suit'] != trump_suit:
            if RANKS.index(card['rank']) > RANKS.index(best_card['rank']):
                best_card = card
                winner = player
    
    return winner

def end_round(game_id):
    game = games[game_id]
    
    game['scores']['team1'] += game['round_scores']['team1']
    game['scores']['team2'] += game['round_scores']['team2']
    
    emit('round_ended', {
        'round_scores': game['round_scores'],
        'total_scores': game['scores'],
        'tricks_won': game['tricks_won']
    }, room=game_id)
    
    game['deck'] = create_deck()
    game['tricks_won'] = {'team1': 0, 'team2': 0}
    start_game(game_id)

@socketio.on('disconnect')
def disconnect():
    for game_id, game in games.items():
        for player in game['players']:
            if player['id'] == request.sid:
                game['players'].remove(player)
                emit('player_left', {'players': game['players']}, room=game_id)
                break

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
