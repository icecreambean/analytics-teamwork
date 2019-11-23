import ast
import sqlite3
import json
import os
import ast
import pandas as pd
from datetime import datetime
from flask import Flask, request, jsonify
from flask_restplus import Resource, Api, fields, inputs, abort
from data_management import metadata_manager
from Create_db import create_connection
#from itsdangerous import JSONWebSignatureSerializer as Serializer
from auth import *
import numpy as np


app = Flask(__name__)
api = Api(app, version='1.5', default="Board Game Geek",
          title="Board Game Geek Dataset", description="...",
          authorizations={
              'API-KEY': {
                  'type': 'apiKey',
                  'in': 'header',
                  'name': 'AUTH-TOKEN'
              }
          },
          security='API-KEY')

mm = metadata_manager.MetaDataManager()

# Get row entries of dataframe, starting from a row index num_rows and extending for
# num_rows. Output can be in dict. All numpy NaN and NA values are converted to
# null / None. A list of dataframe column names can be provided to interpret each element under
# that column as a list.


def get_dict_entries(df, start_pos=None, num_rows=None, keyval_list=[]):
    if start_pos == None:
        start_pos = 0
    end_pos = len(df.index) if (num_rows == None) else min(
        start_pos + num_rows, len(df.index))
    selected = df.iloc[start_pos: end_pos].replace({pd.np.nan: None})
    # all remaining NaN values to be converted to None (client is pure Python)
    # all specified keys to interpret their vals as Python lists (if not None)
    row_entries = selected.to_dict(orient='records')
    if len(keyval_list) > 0:
        for i in range(len(row_entries)):  # row
            for key in keyval_list:  # specified column (key)
                if row_entries[i][key] != None:  # null or list
                    row_entries[i][key] = ast.literal_eval(row_entries[i][key])
    return row_entries


review_model = api.model('Review', {
    'Game_ID': fields.Integer,
    'User': fields.String,
    'Rating': fields.Float,
    'Comment': fields.String,
})

detail_model = api.model('Detail', {
    'Game_ID': fields.Integer,
    'Name': fields.String,
    'Board_Game_Rank': fields.String,
    #'Bayes_Average': fields.Float,
    'Publisher': fields.List(fields.String),
    'Category': fields.List(fields.String),
    'Min_players': fields.Integer,
    'Max_players': fields.Integer,
    'Min_age': fields.Integer,
    'Min_playtime': fields.Integer,
    'Max_playtime': fields.Integer,
    'Description': fields.String,
    'Expansion': fields.List(fields.String),
    'Board_Game_Family': fields.List(fields.String),
    'Mechanic': fields.List(fields.String),
    'Thumbnail': fields.Url,
    'Year_Published': fields.Integer
})

game_model = api.model('Game', {
    'Game_ID': fields.Integer,
    'Name': fields.String,
    'Year': fields.Integer,
    'Rank': fields.Integer,
    'Average': fields.Float,
    'Bayes_Average': fields.Float,
    'Users_Rated': fields.Integer,
    'URL': fields.Url,
    'Thumbnail': fields.Url
})

# Model structure for ML game recommendation
game_suggestion = api.model('GameSuggestion', {
    'Game_ID': fields.Integer,
    'Name': fields.Integer,
    'Category': fields.List(fields.String),
    'Min_players': fields.Integer,
    'Max_players': fields.Integer,
    'Min_age': fields.Integer,
    'Min_playtime': fields.Integer,
    'Max_playtime': fields.Integer,
    'Year_Published': fields.Integer
})


#########################################################################
###GET API STATS###
@api.route('/api_usage')
class Api_Usage(Resource):
    @api.response(200, 'Successful')
    @api.doc(description='Get Api Usage Stats')
    def get(self):
        api_usage = mm.metadata
        mm.increment('/api_usage')
        mm.save()
        return api_usage, 200


#########################################################################
@api.route('/details')
class Board_Games_Details_List(Resource):
    ###GET GAMES DETAILS###
    @api.response(200, 'Successful')
    @api.doc(description='Get all board games details')
    # Chunk this to be loaded onto multiple pages
    def get(self):
        conn = create_connection('Database')
        df = pd.read_sql_query("SELECT * FROM Details;", conn)
        mm.increment('/details')
        mm.save()
        return get_dict_entries(df), 200

    ###POST GAME DETAILS###
    @api.response(201, 'Board Game Details Added Successfully')
    @api.response(400, 'Validation Error')
    @api.doc(description="Add new board game details")
    @api.expect(detail_model, validate=True)
    @requires_auth
    def post(self):
        details = request.json
        for key in details:
            if key not in detail_model.keys():
                return {"message": "Property {} is invalid".format(key)}, 400

        conn = create_connection('Database')

        df = pd.read_sql_query(
            "SELECT Name FROM Details WHERE Game_ID = ?;", conn, params=[details['Game_ID']])                            # Check if the Game_ID already exists
        if len(df) > 0:
            api.abort(400, "Game_ID {} already exists with Name '{}'".format(
                details['Game_ID'], df.loc[0][0]))
        df = pd.read_sql_query(
            "SELECT Game_ID FROM Details WHERE Name = ?;", conn, params=[details['Name']])                             # Check if there is another game with the same Name
        if len(df) > 0:
            api.abort(400, "Game '{}' already exists with Game_ID = {}".format(
                details['Name'], df.loc[0][0]))
        if not (details['Name']):
            api.abort(400, "Name field is missing")
        details['Board_Game_Rank'] = details['Board_Game_Rank'].strip()
        if not (details['Board_Game_Rank']):
            pass
        else:
            try:
                details['Board_Game_Rank'] = int(details['Board_Game_Rank'])
                if details['Board_Game_Rank'] <= 0:
                    api.abort(400, "Rank can't be zero or negative")
            except Exception:
                api.abort(400, "Invalid Rank")
        #if (details['Bayes_Average']) < 0:
            #api.abort(400, "Bayes Average can't be negative")
        if (details['Min_players'] > details['Max_players']):
            api.abort(400, "Maximum players can't be less than Minimum players")
        if (details['Min_players'] <= 0 or details['Max_players'] <= 0):
            api.abort(400, "Number of players can't be zero or negative")
        if (details['Min_age'] < 0):
            api.abort(400, "Invalid age")
        if (details['Min_playtime'] < 0 or details['Max_playtime'] < 0):
            api.abort(400, "Playtime can't be negative")
        if (details['Min_playtime'] > details['Max_playtime']):
            api.abort(400, "Maximum playtime can't be less than Minimum playtime")
        # There are some games that have Year_Published = 2020
        if (details['Year_Published'] > datetime.now().year):
            # (maybe upcoming games, or someone invented a time machine. this condition may change)
            api.abort(400, "Invalid Publishing Year")
        if not (details['Thumbnail']):
            details['Thumbnail'] = 'https://via.placeholder.com/150x150?text=No+Image'

        c = conn.cursor()
        c.execute("INSERT INTO Details(Game_ID, Name, Board_Game_Rank, Publisher, Category, Min_players, Max_players, Min_age, Min_playtime, Max_playtime, Description, Expansion, Board_Game_Family, Mechanic, Thumbnail, Year_Published) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (details['Game_ID'],
                   details['Name'],
                   details['Board_Game_Rank'],
                   #str(details['Bayes_Average']),
                   str(details['Publisher']),
                   str(details['Category']),
                   details['Min_players'],
                   details['Max_players'],
                   details['Min_age'],
                   details['Min_playtime'],
                   details['Max_playtime'],
                   details['Description'],
                   str(details['Expansion']),
                   str(details['Board_Game_Family']),
                   str(details['Mechanic']),
                   details['Thumbnail'],
                   details['Year_Published']))
        conn.commit()
        mm.increment('/board_games_details/POST {}'.format(details['Game_ID']))
        mm.save()
        return {"message": "Game {} is created with ID {}".format(details['Name'], details['Game_ID'])}, 201

    ###UPDATE GAME DETAILS###
    @api.response(404, 'Game not found')
    @api.response(400, 'Validation Error')
    @api.response(200, 'Successful')
    @api.expect(detail_model)
    @api.doc(description="Update a game details by its ID")
    @requires_auth
    def put(self):
        details = request.json
        conn = create_connection('Database')

        df = pd.read_sql_query(
            "SELECT Detail_ID FROM Details WHERE Game_ID = ?", conn, params=[details['Game_ID']])                        # Check if the game exists (Can't update a game that doesn't exist)
        if len(df) == 0:
            api.abort(404, "Game {} doesn't exist".format(details['Game_ID']))
        index = df.loc[0][0]

        df = pd.read_sql_query(
            "SELECT Game_ID FROM Details WHERE Name = ?;", conn, params=[details['Name']])                             # Check if there is another game with the same updated Name
        if len(df) > 0:
            api.abort(400, "Game '{}' already exists with Game_ID={}".format(
                details['Name'], df.loc[0][0]))
        if not (details['Name']):
            api.abort(400, "Name field is missing")
        details['Board_Game_Rank'] = details['Board_Game_Rank'].strip()
        if not (details['Board_Game_Rank']):
            pass
        else:
            try:
                details['Board_Game_Rank'] = int(details['Board_Game_Rank'])
                if details['Board_Game_Rank'] <= 0:
                    api.abort(400, "Rank can't be zero or negative")
            except Exception:
                api.abort(400, "Invalid Rank")
        #if (details['Bayes_Average']) < 0:
            #api.abort(400, "Bayes Average can't be negative")
        if (details['Min_players'] > details['Max_players']):
            api.abort(400, "Maximum players can't be less than Minimum players")
        if (details['Min_players'] <= 0 or details['Max_players'] <= 0):
            api.abort(400, "Number of players can't be zero or negative")
        if (details['Min_age'] < 0):
            api.abort(400, "Invalid age")
        if (details['Min_playtime'] < 0 or details['Max_playtime'] < 0):
            api.abort(400, "Playtime can't be negative")
        if (details['Min_playtime'] > details['Max_playtime']):
            api.abort(400, "Maximum playtime can't be less than Minimum playtime")
        if (details['Year_Published'] > datetime.now().year):
            api.abort(400, "Invalid Publishing Year")
        if not (details['Thumbnail']):
            details['Thumbnail'] = 'https://via.placeholder.com/150x150?text=No+Image'

        for key in details:
            if key not in detail_model.keys():
                return {"message": "Property {} is invalid".format(key)}, 400

        c = conn.cursor()
        c.execute('UPDATE Details SET Name=?, Board_Game_Rank=?, Publisher=?, Category=?, Min_players=?, Max_players=?, Min_age=?, Min_playtime=?, Max_playtime=?, Description=?, Expansion=?, Board_Game_Family=?, Mechanic=?, Thumbnail=?, Year_Published=? WHERE Detail_ID=?;', (
            str(details['Name']),
            str(details['Board_Game_Rank']),
            #str(details['Bayes_Average']),
            str(details['Publisher']),
            str(details['Category']),
            details['Min_players'],
            details['Max_players'],
            details['Min_age'],
            details['Min_playtime'],
            details['Max_playtime'],
            str(details['Description']),
            str(details['Expansion']),
            str(details['Board_Game_Family']),
            str(details['Mechanic']),
            str(details['Thumbnail']),
            details['Year_Published'],
            int(index)))

        conn.commit()
        mm.increment('/board_games_details/PUT {}'.format(details['Game_ID']))
        mm.save()

        return {"message": "Game {} has been successfully updated".format(details['Game_ID'])}, 200


@api.route('/details/<int:id>')
@api.param('id', 'Game ID')
class Board_Games(Resource):
    ###GET GAME DETAILS BY ID###
    @api.response(404, 'Game not found')
    @api.response(200, 'Successful')
    @api.doc(description="Get a game details by its ID")
    def get(self, id):
        conn = create_connection('Database')
        df = pd.read_sql_query(
            "SELECT * FROM Details WHERE Game_ID = ?;", conn, params=[id])
        if len(df) == 0:
            api.abort(404, "Game {} doesn't exist".format(id))
        details = df.loc[0].to_json()
        details = json.loads(details)

        mm.increment('/board_games_details/{}'.format(id))
        mm.save()
        return details, 200


@api.route('/details/<string:name>')
@api.param('name', 'Game Name')
class Board_Games_Name(Resource):
    ###GET GAME DETAILS BY NAME###
    @api.response(404, 'Game not found')
    @api.response(200, 'Successful')
    @api.doc(description="Get a game details by its name")
    def get(self, name):
        conn = create_connection('Database')
        df = pd.read_sql_query(
            "SELECT * FROM Details WHERE Name LIKE ?;", conn, params=['%' + name + '%'])
        if len(df) == 0:
            api.abort(404, "No Match Found - {}".format(name))
        mm.increment('/board_games_details/{}'.format(name))
        mm.save()
        return get_dict_entries(df), 200


@api.route('/details/year/<string:year>')
@api.param('year', 'Game Year of Publishing')
class Board_Games_Year(Resource):
    ###GET GAMES DETAILS BY YEAR OF PUBLISHING###
    @api.response(404, 'No Games Published That Year')
    @api.response(200, 'Successful')
    @api.doc(description="Get all games details by publishing year")
    def get(self, year):
        try:
            year = int(year)
        except Exception:
            api.abort(400, "Invalid year")

        conn = create_connection('Database')
        df = pd.read_sql_query(
            "SELECT * FROM Details WHERE Year_Published = ? ORDER BY Year_Published;", conn, params=[year])
        if len(df) == 0:
            api.abort(404, "No Games Published In Year {}".format(year))

        mm.increment('/board_games_year/{}'.format(year))
        mm.save()
        return get_dict_entries(df), 200


#########################################################################
@api.route('/reviews')
class addReviews(Resource):
    ###POST REVIEW###
    @api.response(201, 'Review Added Successfully')
    @api.response(400, 'Validation Error')
    @api.doc(description="Add a new review")
    @api.expect(review_model, validate=True)
    @requires_auth
    def post(self):
        review = request.json

        for key in review:
            if key not in review_model.keys():
                return {"message": "Property {} is invalid".format(key)}, 400

        conn = create_connection('Database')
        df = pd.read_sql_query(
            "SELECT Name FROM Details WHERE Game_ID = ?;", conn, params=[review['Game_ID']])
        if len(df) == 0:
            api.abort(404, "Game {} doesn't exist".format(review['Game_ID']))
        if (review['Rating'] < 1 or review['Rating'] > 10):
            api.abort(400, "Rating must be between 1 and 10")

        Name = df.loc[0][0]
        c = conn.cursor()
        c.execute("INSERT INTO Reviews(User, Rating, Game_ID, Comment, Name) VALUES(?,?,?,?,?)",
                  (review['User'], review['Rating'], review['Game_ID'], review['Comment'], Name))
        last_row = c.lastrowid
        conn.commit()
        mm.increment('/reviews/POST {}'.format(review['Game_ID']))
        mm.save()
        return {"message": "Review for '{}' Game_ID={} has been added with Review_ID={}".format(Name, review['Game_ID'], last_row)}, 201


@api.route('/reviews/<int:id>')
@api.param('id', 'Game ID')
class Reviews(Resource):
    ###GET REVIEWS FOR A GAME###
    @api.response(404, 'Review not found')
    @api.response(200, 'Successful')
    @api.doc(description="Get all reviews for a specific game")
    def get(self, id):
        conn = create_connection('Database')
        df = pd.read_sql_query(
            "SELECT Name FROM Details WHERE Game_ID = ?;", conn, params=[id])
        if len(df) == 0:
            api.abort(404, "Game {} doesn't exist".format(id))
        df = pd.read_sql_query(
            "SELECT * FROM Reviews WHERE Game_ID = ?;", conn, params=[id])
        if len(df) == 0:
            api.abort(404, "Game {} has no reviews".format(id))

        mm.increment('/reviews/{}'.format(id))
        mm.save()
        return get_dict_entries(df), 200

#########################################################################
# can be changed to include the number of top games the user wants /details/top/{int}
@api.route('/details/top10')
class Board_Games_Details_Top10List(Resource):
    ###GET TOP 10 GAMES DETAILS###
    @api.response(200, 'Successful')
    @api.doc(description='Get Top 10 board games details')
    def get(self):
        conn = create_connection('Database')
        df = pd.read_sql_query(
            "SELECT * FROM Details WHERE Board_Game_Rank != 'null' AND Board_Game_Rank > 0 ORDER BY Board_Game_Rank LIMIT 10;", conn)
        mm.increment('/details/top10')
        mm.save()
        return get_dict_entries(df)


# doesn't use the Games table since none of the endpoints use that table either
# def get_game_averages(conn):
#     df = pd.read_sql_query("select Game_ID, avg(Rating) as Average, count(*) as Num_Reviews from Reviews group by Game_ID order by Average desc limit 4", 
#                            conn, index_col='Game_ID')
#     return df.to_dict(orient='index')

# too difficult to implement by year AND by category as the db is not properly relational
@api.route('/details/top_yearly')
class Board_Games_Details_TopYearlyGame(Resource):
    ###GET TOP GAME OF EACH YEAR###
    @api.response(200, 'Successful')
    @api.doc(description='Get the top-rated game for each year, alongside its ID, name, average score, and number of reviews counted. Years in BC will be negative.')
    def get(self):
        conn = create_connection('Database')
        sql = '''
select *
from (select Game_ID, Name, Year_Published as Year from Details) natural join 
     (select Game_ID, avg(Rating) as Average, count(*) as Num_Reviews from Reviews group by Game_ID) 
group by Year
having max(Average)
order by Year asc;'''
        df = pd.read_sql_query(sql, conn)
        return get_dict_entries(df)


@api.route('/trends/num_published')
class Trends_Yearly_Published(Resource):
    ###GET NUMBER OF GAMES PUBLISHED PER YEAR###
    @api.response(200, 'Successful')
    @api.doc(description='Get the number of game publications per year. Years in BC will be negative.')
    def get(self):
        conn = create_connection('Database')
        df = pd.read_sql_query(
            "select Year_Published as Year, count(*) as Number_Published from Details group by Year_Published order by Year_Published;", conn)
        mm.increment('/trends/num_published')
        mm.save()
        return get_dict_entries(df)


@api.route('/trends/rating_stats')
class Trends_Rating_Statistics(Resource):
    ###GET BOX PLOT OF RATINGS PER YEAR###
    @api.response(200, 'Successful')
    @api.doc(description='Gets the min, max, median, 1st percentile, 3rd percentile and the average of all board game ratings for each year.')
    def get(self):
        # cached from gen_review_stats.py due to compute time requirements
        with open('review_rating_quantiles.json','r') as f:
            stats = json.load(f)
        return stats


#########################################################################
###GET GAME RECOMMENDATIONS###
# Get recommendations by name
@api.route('/recommendations/<int:id>')
@api.param('id', 'Game ID')
class Recommendations(Resource):
    @api.response(200, 'Successful')
    @api.response(404, 'No Recommendations Found')
    # @api.expect(game_suggestion)
    @api.doc(
        description="Get recommendations for a specific game",
        params={
            'Name': "Name of the Board Game",
            'Category': "List of board game categories",
            'Min_players': 'Minimum number of players',
            'Max_players': 'Maximum number of players',
            'Min_age': 'Minimum recommended age',
            'Min_playtime': 'Minimum playtime',
            'Max_playtime': 'Maximum playtime',
            'Min_Year_Published': 'Min Year Published',
            'Max_Year_Published': 'Max Year Published'
        })
    def get(self, id):
        details = request.args
        print(details)

        conn = create_connection('Database')
        df = pd.read_sql_query(
            "SELECT Name FROM Details WHERE Game_ID = ?;", conn, params=[id])
        if len(df) == 0:
            api.abort(404, "Game {} doesn't exist".format(id))
        name = df.loc[0][0]


        # Get reviews
        # Open recommendations
        if not os.path.exists('recommendations.json'):
            api.abort(404, "Recommendations file doesn't exist")

        # Get list of recommendations
        try:
            result = getRecommendationByName(name)
        except KeyError:
            print('KEY ERROR')
            api.abort(404, "Name was not found")
        # print(result)
        # Do series of filters
        try:
            if 'Min_Year_Published' in details:
                value = int(details['Min_Year_Published'])
                result = result[result['yearpublished'] >= value]
            if 'Max_Year_Published' in details:
                value = int(details['Max_Year_Published'])
                result = result[result['yearpublished'] <= value]
            if 'Min_players' in details:
                value = int(details['Min_players'])
                result = result[result["minplayers"] >= value]
            if 'Max_players' in details:
                value = int(details['Max_players'])
                result = result[result["maxplayers"] <= value]
            if 'Min_playtime' in details:
                value = int(details['Min_playtime'])
                result = result[result["minplaytime"] >= value]
            if 'Max_playtime' in details:
                value = int(details['Max_playtime'])
                result = result[result["maxplaytime"] <= value]
            if 'Category' in details:
                values = ast.literal_eval(details['Category'])
                result['boardgamecategory'] = result['boardgamecategory'].replace(np.nan, '[]')
                result = result[result['boardgamecategory'].apply(lambda x: set(ast.literal_eval(x)).issuperset(set(values)) )]
        except:
            api.abort(400, 'Bad Request')

        return get_dict_entries(result)

# Returns a df with recommendations
def getRecommendationByName(name):
    with open('recommendations.json') as json_data:
        games = json.load(json_data)
    json_data.close()

    games = games[name]
    # print(games)

    details = pd.read_csv("2019-05-02.csv")
    top200 = details[details['Name'].isin(games)]
    top200 = top200[["ID","Name"]]
    player_detail = pd.read_csv("games_detailed_info.csv")
    df = pd.merge(left=player_detail,right=top200,left_on='id',right_on='ID')
    df = df[["ID","Name","boardgamepublisher","boardgamecategory","minplayers","maxplayers","minplaytime","maxplaytime","minage","description","boardgameexpansion","boardgamemechanic","thumbnail","yearpublished"]]
    return df
    

#########################################################################
@api.route('/auth')
class Token(Resource):
    @api.response(200, 'Successful')
    @api.doc(description="Get a token to access the end points")
    def get(self):
        return {'token': auth.generate_token().decode()}, 200


#########################################################################
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8000, debug=True)

    # conn = create_connection('Database')
    # df = pd.read_sql_query("SELECT Rating FROM Reviews WHERE Rating = 1;", conn)
    # if len(df) == 0:
    #     print("Game 200 doesn't exist")
    # print(df)
    # Name = df.loc[0][0]
    # if not os.path.exists('recommendations.json'):
    #     print("Recommendations file doesn't exist")
    # with open('recommendations.json') as json_file:
    #     #json_string = json.dumps(json_file)
    #     rec = json.load(json_file)
    # if Name not in rec:
    #     print("No recommendations found for {}".format(Name))
    # print(rec[Name])
