#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Aug 23 17:34:22 2021

@author: matthew
"""


# Imports
import numpy as np
from pathlib import Path
import glob
import os

import tensorflow as tf
import tensorflow.keras as keras

from tensorflow.keras.applications.vgg16 import VGG16
from tensorflow.keras import Input, Model
from tensorflow.keras import losses, optimizers
from tensorflow.keras.utils import plot_model

from vudlnet21.neural_net import train_double_network, define_two_head_model, file_list_divider, file_merger, open_VolcNet_file
from vudlnet21.plotting import custom_training_history , plot_data_class_loc_caller

#%% Things to set

# settings that need to be the same as part 1
project_outdir = Path('./01_toy_example')
synthetic_ifgs_settings = {'defo_sources' : ['dyke', 'sill', 'no_def']}               # deformation patterns that will be included in the dataset.  

# step 05 (compute bottleneck features): 
                                                                                        # no settings here.  
    
# step 06 (train the fully connected part of the network)
cnn_settings = {}
cnn_settings['n_files_train']     = 22                                              # the number of files that will be used to train the network
cnn_settings['n_files_validate']  = 2                                               # the number of files that wil be used to validate the network (i.e. passed through once per epoch)
cnn_settings['n_files_test']      = 2                                               # the number of files held back for testing.  
fc_loss_weights = [0.05, 0.95]                                                      # the relative weighting of the two losses (classificaiton and localisation) to contribute to the global loss.  Classification first, localisation second.  
n_epochs_fc = 10                                                                    # the number of epochs to train the fully connected network for (ie. the number of times all the training data are passed through the model)

# step 07 (fine-tune the 5th block and the fully connected part of the network):
block5_loss_weights = [0.05, 0.95]                                                  # as per fc_loss_weights, but by changing these more emphasis can be placed on either the clasification or localisation loss.  
#block5_lr = 1.5e-8                                                                  # a pretty important parameter.  We have to set a learning rate manually as an adaptive approach (e.g. NADAM) will be high initially, and therefore make large updates that will wreck the model (as we're just fine-tuning a model so have something good to start with)
block5_lr = 1.0e-6                                                                  # a pretty important parameter.  We have to set a learning rate manually as an adaptive approach (e.g. NADAM) will be high initially, and therefore make large updates that will wreck the model (as we're just fine-tuning a model so have something good to start with)
n_epochs_block5 = 10                                                                 # the number of epochs to fine-tune for (ie. the number of times all the training data are passed through the model)



#%% 5: Compute bottlenceck features (i.e. pass the data through the 5 computationally expensive convolutional blocks of VGG16 to create the feature vectors ( normally 224x224x3 -> 7x7x512))

print("\nStep 05: Computing the bottleneck features.")


# vgg16_block_1to5 = VGG16(weights='imagenet', include_top=False, input_shape = (224,224,3))          # load the first 5 (convolutional) blocks of VGG16 and their weights.  
# data_out_files = sorted(glob.glob(str(project_outdir / 'step_04_merged_rescaled_data/*.npz')))                           # get a list of the files output by step 05 (augmented real data and synthetic data mixed and rescaed to correct range, with 0s for masked areas.  )

# for file_n, data_out_file in enumerate(data_out_files):                                             # loop through each of the step 05 files.  
#     print(f'Bottlneck file {file_n}:')    
#     data_out_file = Path(data_out_file)                                                                                     # convert to path 
#     bottleneck_file_name = data_out_file.parts[-1].split('.')[0]                                                            # and get last part which is filename    
#     data = np.load(data_out_file)                                                                                           # load the numpy file
#     X = data['X']                                                                                                           # extract the data for it
#     Y_class = data['Y_class']                                                                                               # and class labels.  
#     Y_loc = data['Y_loc']                                                                                                   # and location labels.  
#     X_btln = vgg16_block_1to5.predict(X, verbose = 1)                                                                       # predict up to bottleneck    
#     np.savez(project_outdir / 'step_05_bottleneck' / f"{bottleneck_file_name}_bottleneck.npz", X = X_btln, Y_class = Y_class, Y_loc = Y_loc)     # save the bottleneck file, and the two types of label.  


#%% 6: Train the fully connected part of the CNN

print('\nStep 06: Training the fully connected part of the CNN using the bottleneck features.')

# 6.1 deal with files
data_files = sorted(glob.glob(str(project_outdir / 'step_04_merged_rescaled_data' / '*npz')), key = os.path.getmtime)                  # make list of data files
bottleneck_files = sorted(glob.glob(str(project_outdir / 'step_05_bottleneck' / '*npz')), key = os.path.getmtime)                      # and make a list of bottleneck files (ie files that have been passed through the first 5 blocks of vgg16)

if len(data_files) < (cnn_settings['n_files_train'] + cnn_settings['n_files_validate'] + cnn_settings['n_files_test']):
    raise Exception(f"There are {len(data_files)} data files, but {cnn_settings['n_files_train']} have been selected for training, "
                    f"{cnn_settings['n_files_validate']} for validation, and {cnn_settings['n_files_test']} for testing, "
                    f"which sums to greater than the number of data files.  Perhaps adjust the number of files used for the training stages? "
                    f"For now, exiting.")

data_files_train, data_files_validate, data_files_test = file_list_divider(data_files, cnn_settings['n_files_train'], cnn_settings['n_files_validate'], cnn_settings['n_files_test'])                              # divide the files into train, validate and test
bottleneck_files_train, bottleneck_files_validate, bottleneck_files_test = file_list_divider(bottleneck_files, cnn_settings['n_files_train'], cnn_settings['n_files_validate'], cnn_settings['n_files_test'])      # also divide the bottleneck files

X_validate, Y_class_validate, Y_loc_validate      = file_merger(data_files_validate)                             # Open all the validation data to RAM
X_validate_btln, Y_class_validate, Y_loc_validate = file_merger(bottleneck_files_validate)                       # Open the validation data bottleneck features to RAM
X_test, Y_class_test, Y_loc_test                  = file_merger(data_files_test)                                 # Open the test data to RAM
X_test_btln, Y_class_test_btln, Y_loc_test_btln   = file_merger(bottleneck_files_test)                           # Open the test data bottleneck features to RAM

print(f"    There are {len(data_files)} data files.  {len(data_files_train)} will be used for training,"         # print to terminal status on how many files will be used etc.  
      f"{len(data_files_validate)} for validation, and {len(data_files_test)} for testing.  ")

# 6.2 define, compile, and train the model
vgg16_block_1to5 = VGG16(weights='imagenet', include_top=False, input_shape = (224,224,3))                        # VGG16 is used for its convolutional layers and weights (but no fully connected part as we define out own )
fc_model_input = Input(shape = vgg16_block_1to5.output_shape[1:])                                                 # the input to the fully connected model must be the same shape as the output of the 5th block of vgg16
output_class, output_loc = define_two_head_model(fc_model_input, len(synthetic_ifgs_settings['defo_sources']))    # build the full connected part of the model, and get the two model outputs
vgg16_2head_fc = Model(inputs=fc_model_input, outputs=[output_class, output_loc])                                 # define the model.  Input is the shape of vgg16 block 1 to 5 output, and there are two outputs (hence list)                                
plot_model(vgg16_2head_fc, to_file=project_outdir / 'step_06_train_fully_connected_model' / 'vgg16_2head_fc.png',                     # also plot the model.  This funtcion is known to be fragile due to Graphviz dependencies.  
           show_shapes = True, show_layer_names = True)

loss_class = losses.categorical_crossentropy                                                                      # good loss to use for classification problems, may need to switch to binary if only two classes though?
loss_loc = losses.mean_squared_error                                                                              # loss for localisation
opt_used = optimizers.Nadam(clipnorm = 1., clipvalue = 0.5)                                                       # adam with Nesterov accelerated gradient
vgg16_2head_fc.compile(optimizer = opt_used, loss=[loss_class, loss_loc],                                         # compile the model
                       loss_weights = fc_loss_weights, metrics=['accuracy'])                                      # accuracy is useful to have on the terminal during training

vgg16_2head_fc,  metrics_class_fc, metrics_localisation_fc, metrics_combined_loss_fc = train_double_network(vgg16_2head_fc, bottleneck_files_train,
                                                                                                            n_epochs_fc, ['class_dense3_loss', 'loc_dense6_loss'],
                                                                                                            X_validate_btln, Y_class_validate, Y_loc_validate, len(synthetic_ifgs_settings['defo_sources']))

custom_training_history(metrics_class_fc, n_epochs_fc, title = 'Fully connected classification training')          # plot of the training process for classification
custom_training_history(metrics_localisation_fc, n_epochs_fc, title = 'Fully connected localisation training')     # plot of the training process for localisation
vgg16_2head_fc.save_weights(project_outdir / 'step_06_train_fully_connected_model' / 'vgg16_2head_fc.h5')                              # save the weights of the model we have trained

# 6.3 Test the model
Y_class_test_cnn, Y_loc_test_cnn = vgg16_2head_fc.predict(X_test_btln, verbose = 1)                                # forward pass of the testing data bottleneck features through the fully connected part of the model
plot_data_class_loc_caller(X_test, classes = Y_class_test, classes_predicted = Y_class_test_cnn,                    # plot all the testing data
                           locs = Y_loc_test, locs_predicted = Y_loc_test_cnn, 
                           source_names = synthetic_ifgs_settings['defo_sources'], window_title = 'Testing data (after step 06)')


#%% Step 07: Fine-tune the 5th convolutional block and the fully connected network.  

vgg16_block_1to5 = VGG16(weights='imagenet', include_top=False, input_shape = (224,224,3))                                       # VGG16 is used for its convolutional layers and weights (but no fully connected part as we define out own )
output_class, output_loc = define_two_head_model(vgg16_block_1to5.output, len(synthetic_ifgs_settings['defo_sources']))          # build the fully connected part of the model, and get the two model outputs

vgg16_2head = Model(inputs=vgg16_block_1to5.input, outputs=[output_class, output_loc])                                           # define the full model
vgg16_2head.load_weights(project_outdir / 'step_06_train_fully_connected_model' / 'vgg16_2head_fc.h5', by_name = True)                               # load the weights for the fully connected part which were trained in step 06 (by_name flag so that it doesn't matter that the models are different sizes))

for layer in vgg16_2head.layers[:15]:                                                                                             # freeze blocks 1-4 (ie, we are only fine tuneing the 5th block and the fully connected part of the network)
    layer.trainable = False    

#block5_optimiser = optimizers.RMSprop(lr=block5_lr)                                      
block5_optimiser = optimizers.SGD(lr=block5_lr, momentum=0.9)                                            # set the optimizer used in this training part.  Note have to set a learning rate manualy as an adaptive one (eg Nadam) would wreck model weights in the first few passes before it reduced.  
vgg16_2head.compile(optimizer = block5_optimiser, metrics=['accuracy'],                                  # recompile as we've changed which layers can be trained/ optimizer etc.  
                    loss=[loss_class, loss_loc], loss_weights = block5_loss_weights)                                  

try:
    plot_model(vgg16_2head, to_file=project_outdir / 'step_06_train_fully_connected_model' / 'vgg16_2head.png', show_shapes = True, show_layer_names = True)      # try to make a graphviz style image showing the complete model 
except:
    print(f"Failed to create a .png of the model, but continuing anyway.  ")                               # this can easily fail, however, so simply alert the user and continue.  


print('\n\nFine-tuning the 5th convolutional block and the fully connected network.')
vgg16_2head, metrics_class_5th, metrics_localisation_5th, metrics_combined_loss_5th = train_double_network(vgg16_2head, data_files_train,
                                                                                                           n_epochs_block5, ['class_dense3_loss', 'loc_dense6_loss'],
                                                                                                           X_validate, Y_class_validate, Y_loc_validate, len(synthetic_ifgs_settings['defo_sources']))

custom_training_history(metrics_class_5th, n_epochs_block5, title = '5th block classification training')
custom_training_history(metrics_localisation_5th, n_epochs_block5, title = '5th block localisation training')

vgg16_2head.save(project_outdir / 'step_07_train_full_model' / '01_vgg16_2head_block5_trained.h5')
np.savez(project_outdir / 'step_07_train_full_model' / 'training_history.npz', metrics_class_fc = metrics_class_fc,
                                                         metrics_localisation_fc = metrics_localisation_fc,
                                                         metrics_combined_loss_fc = metrics_combined_loss_fc,
                                                         metrics_class_5th = metrics_class_5th,
                                                         metrics_localisation_5th = metrics_localisation_5th,
                                                         metrics_combined_loss_5th = metrics_combined_loss_5th)




#%% Step 08: Test with synthetic and real data

print('\n\nStep 08: Forward pass of the testing data through the network:')

Y_class_test_cnn, Y_loc_test_cnn = vgg16_2head.predict(X_test[:,:,:,:], verbose = 1)                                    # predict class labels


plot_data_class_loc_caller(X_test, classes = Y_class_test, classes_predicted = Y_class_test_cnn,                    # plot all the testing data
                           locs = Y_loc_test, locs_predicted = Y_loc_test_cnn, 
                           source_names = synthetic_ifgs_settings['defo_sources'], window_title = 'Testing data (after step 07)')