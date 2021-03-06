import sys, os
# assumes running from main directory
sys.path.append(os.path.abspath("./"))

import time, random
import numpy as np
import sugartensor as tf
import matplotlib.pyplot as plt
from tensorflow.contrib import layers as tflayers

# from testing import test
from shared_utils.data import *
import datetime as dt


class ROLO_TF:
    # Buttons
    validate = True
    validate_step = 2000
    display_validate = True
    save_step = 1000
    bidirectional = False
    display_step = 250
    restore_weights = True
    display_coords = False
    display_iou_penalty = True
    use_attention = False
    coord_scale = 5.0
    object_scale = 1.0
    noobject_scale = .5

    output_validation_images = False

    iou_with_ground_truth = True
    display_object_loss = True
    display_regu = False
    confidence_detection_threshold = .5
    # Magic numbers
    learning_rate = 0.00005
    lamda = .3

    # Path
    rolo_weights_file = 'weights/causal_yolo_weights.ckpt'
    rolo_current_save = 'weights/causal_yolo_weights_temp.ckpt'

    # Vector for very small model
    len_feat = 1080
    # Vector for 4096 features model
    # len_feat = 4096
    len_predict = 6
    len_coord = 4
    len_vec = len_feat + len_predict

    # Batch
    nsteps = 3
    batchsize = 16
    n_iters = 100000
    batch_offset = 0

    # Data
    x = tf.placeholder("float32", [None, nsteps, len_vec])
    y = tf.placeholder("float32", [None, len_coord])

    list_batch_pairs = []

    # Initializing
    def __init__(self, kwargs):
        # TODO: do this the proper way **kwargs
        print("ROLO Initializing")
        if 'num_layers' in kwargs:
            self.number_of_layers = kwargs['num_layers']
        if 'bidirectional' in kwargs:
            self.bidirectional = kwargs['bidirectional']

        self.ROLO()


    def dnn_layers(self, input_layers, layers, activation=tf.sigmoid):
        # layers = dimension of layers
        return tflayers.stack(input_layers, tflayers.fully_connected, layers, activation_fn=activation)

    # Routines: Network
    def LSTM(self, name,  _X):
        # import pdb; pdb.set_trace()
        ''' shape: (batchsize, nsteps, len_vec) '''
        _X = tf.transpose(_X, [1, 0, 2])
        # ''' shape: (nsteps, batchsize, len_vec) '''
        # _X = tf.reshape(_X, [self.nsteps * self.batchsize, self.len_vec])
        # ''' shape: n_steps * (batchsize, len_vec) '''
        # _X = tf.split(_X, num_or_size_splits=self.nsteps, axis=0)

        latent_dimensions = self.len_vec
        num_blocks = 1


        def res_block(tensor, size, rate, dim=latent_dimensions):

            # filter convolution
            conv_filter = tensor.sg_aconv1d(size=size, rate=rate, act='tanh', bn=True)

            # gate convolution
            conv_gate = tensor.sg_aconv1d(size=size, rate=rate,  act='sigmoid', bn=True)

            # output by gate multiplying
            out = conv_filter * conv_gate

            # final output
            out = out.sg_conv1d(size=1, dim=dim, act='tanh', bn=True)

            # residual and skip output
            return out + tensor, out

        # expand dimension
        z = _X.sg_conv1d(size=1, dim=latent_dimensions, act='tanh', bn=True)

        # dilated conv block loop
        skip = 0  # skip connections
        for i in range(num_blocks):
            for r in [1, 2]:
                z, s = res_block(z, size=3, rate=r)
                skip += s

        # final logit layers
        logit = (skip
                 .sg_conv1d(size=1, act='tanh', bn=True)
                 .sg_conv1d(size=1, dim=5)) #5 => 4 coords + confidence

        # import pdb; pdb.set_trace()
        # dense_coords_conf = self.dnn_layers(pred[-1], (self.len_vec, 256, 32, self.len_coord+1), activation=tf.sigmoid)
        #
        # batch_pred_feats = pred[0][:, 0:self.len_feat]
        # batch_pred_coords = dense_coords_conf[:, 0:4]
        # batch_pred_confs = dense_coords_conf[:,4]
        # import pdb; pdb.set_trace()
        batch_pred_coords = logit[-1][:,0:4]
        batch_pred_confs = logit[-1][:,4]

        return None, batch_pred_coords, batch_pred_confs, None


    def iou(self, boxes1, boxes2):
        """
        Note: Modified from https://github.com/nilboy/tensorflow-yolo/blob/python2.7/yolo/net/yolo_net.py
        calculate ious
        Args:
          boxes1: 4-D tensor [CELL_SIZE, CELL_SIZE, BOXES_PER_CELL, 4]  ====> (x_center, y_center, w, h)
          boxes2: 1-D tensor [4] ===> (x_center, y_center, w, h)
        Return:
          iou: 3-D tensor [CELL_SIZE, CELL_SIZE, BOXES_PER_CELL]
        """
        boxes1 = tf.stack([boxes1[:,0] - boxes1[:,2] / 2, boxes1[:,1] - boxes1[:,3] / 2,
                          boxes1[:,0] + boxes1[:,2] / 2, boxes1[:,1] + boxes1[:,3] / 2])

        boxes2 =  tf.stack([boxes2[:,0] - boxes2[:,2] / 2, boxes2[:,1] - boxes2[:,3] / 2,
                          boxes2[:,0] + boxes2[:,2] / 2, boxes2[:,1] + boxes2[:,3] / 2])

        #calculate the left up point

        lu = tf.maximum(boxes1[0:2], boxes2[0:2])
        rd = tf.minimum(boxes1[2:], boxes2[2:])

        #intersection
        intersection = rd - lu

        inter_square = tf.multiply(intersection[0],intersection[1])

        mask = tf.cast(intersection[0] > 0, tf.float32) * tf.cast(intersection[1] > 0, tf.float32)

        inter_square = tf.multiply(mask,inter_square)

        #calculate the boxs1 square and boxs2 square
        square1 = tf.multiply((boxes1[2] - boxes1[0]) ,(boxes1[3] - boxes1[1]))
        square2 = tf.multiply((boxes2[2] - boxes2[0]),(boxes2[3] - boxes2[1]))

        return inter_square/(square1 + square2 - inter_square + 1e-6), inter_square



    # Routines: Train & Test
    def train(self):
        ''' Network '''
        batch_pred_feats, batch_pred_coords, batch_pred_confs, self.final_state = self.LSTM('lstm', self.x)

        iou_predict_truth, intersection = self.iou(batch_pred_coords, self.y[:,0:4])

        should_exist = I = tf.cast(tf.reduce_sum(self.y[:,0:4], axis=1) > 0., tf.float32)
        no_I = tf.ones_like(I, dtype=tf.float32) - I

        object_loss = tf.nn.l2_loss(I * (batch_pred_confs - iou_predict_truth)) * self.object_scale
        noobject_loss = tf.nn.l2_loss(no_I * (batch_pred_confs - iou_predict_truth)) * self.noobject_scale

        p_sqrt_w = tf.sqrt(tf.minimum(1.0, tf.maximum(0.0, batch_pred_coords[:, 2])))
        p_sqrt_h = tf.sqrt(tf.minimum(1.0, tf.maximum(0.0, batch_pred_coords[:, 3])))

        sqrt_w = tf.sqrt(tf.abs(self.y[:,2]))
        sqrt_h = tf.sqrt(tf.abs(self.y[:,3]))

        loss = (tf.nn.l2_loss(I*(batch_pred_coords[:,0] - self.y[:,0])) +
                 tf.nn.l2_loss(I*(batch_pred_coords[:,1] - self.y[:,1])) +
                 tf.nn.l2_loss(I*(p_sqrt_w - sqrt_w)) +
                 tf.nn.l2_loss(I*(p_sqrt_h - sqrt_h))) * self.coord_scale

        #max_iou = tf.nn.l2_loss(I*(tf.ones_like(iou_predict_truth, dtype=tf.float32) - iou_predict_truth))

        total_loss = loss + object_loss + noobject_loss #+ max_iou

        ''' Optimizer '''
        optimizer = tf.train.AdamOptimizer(learning_rate=self.learning_rate).minimize(total_loss) # Adam Optimizer

        ''' Summary for tensorboard analysis '''
        dataset_loss = -1
        dataset_loss_best = 100
        test_writer = tf.summary.FileWriter('summary/test')
        tf.summary.scalar('dataset_loss', dataset_loss)
        summary_op = tf.summary.merge_all()

        ''' Initializing the variables '''
        self.saver = tf.train.Saver()
        batch_states = np.zeros((self.batchsize, 2*self.len_vec))

        # TODO: make this a command line argument, etc.
        # training set loader
        batch_loader = BatchLoader("./DATA/TRAINING/", seq_len=self.nsteps, batch_size=self.batchsize, step_size=1, folders_to_use=["GOPR0005","GOPR0006","GOPR0008","GOPR0008_2","GOPR0009","GOPR0009_2","GOPR0010","GOPR0011","GOPR0012","GOPR0013","GOPR0014","GOPR0015","GOPR0016","MVI_8607","MVI_8609","MVI_8610","MVI_8612","MVI_8614","MVI_8615","MVI_8616"])
        validation_set_loader = BatchLoader("./DATA/VALID/", seq_len=self.nsteps, batch_size=self.batchsize, step_size=1, folders_to_use=["bbd_2017__2017-01-09-21-40-02_cam_flimage_raw","bbd_2017__2017-01-09-21-44-31_cam_flimage_raw","bbd_2017__2017-01-09-21-48-46_cam_flimage_raw","bbd_2017__2017-01-10-16-07-49_cam_flimage_raw","bbd_2017__2017-01-10-16-21-01_cam_flimage_raw","bbd_2017__2017-01-10-16-31-57_cam_flimage_raw","bbd_2017__2017-01-10-21-43-03_cam_flimage_raw","bbd_2017__2017-01-11-20-21-32_cam_flimage_raw","bbd_2017__2017-01-11-21-02-37_cam_flimage_raw"])

        print("%d available training batches" % len(batch_loader.batches))
        print("%d available validation batches" % len(validation_set_loader.batches))

        ''' Launch the graph '''
        with tf.Session() as sess:
            if self.restore_weights == True and os.path.isfile(self.rolo_current_save + ".index"):
                # sess.run(init)
                tf.sg_init(sess)
                self.saver.restore(sess, self.rolo_current_save)
                print("Weight loaded, finetuning")
            else:
                # sess.run(init)
                tf.sg_init(sess)
                print("Training from scratch")

            epoch_loss = []
            for self.iter_id in range(self.n_iters):
                ''' Load training data & ground truth '''
                batch_id = self.iter_id - self.batch_offset

                batch_xs, batch_ys, _ = batch_loader.load_batch(batch_id)

                ''' Update weights by back-propagation '''

                sess.run(optimizer, feed_dict={self.x: batch_xs,
                                               self.y: batch_ys})

                if self.iter_id % self.display_step == 0:
                    ''' Calculate batch loss '''
                    batch_loss = sess.run(total_loss,
                                          feed_dict={self.x: batch_xs,
                                                     self.y: batch_ys})
                    epoch_loss.append(batch_loss)
                    print("Total Batch loss for iteration %d: %.9f" % (self.iter_id, batch_loss))

                if self.iter_id % self.display_step == 0:
                    ''' Calculate batch loss '''
                    batch_loss = sess.run(loss,
                                          feed_dict={self.x: batch_xs,
                                                     self.y: batch_ys})
                    print("Bounding box coord error loss for iteration %d: %.9f" % (self.iter_id, batch_loss))

                if self.display_object_loss and self.iter_id % self.display_step == 0:
                    ''' Calculate batch object loss '''
                    batch_o_loss = sess.run(object_loss,
                                          feed_dict={self.x: batch_xs,
                                                     self.y: batch_ys})
                    print("Object loss for iteration %d: %.9f" % (self.iter_id, batch_o_loss))

                if self.display_object_loss and self.iter_id % self.display_step == 0:
                    ''' Calculate batch object loss '''
                    batch_noo_loss = sess.run(noobject_loss,
                                          feed_dict={self.x: batch_xs,
                                                     self.y: batch_ys})
                    print("No Object loss for iteration %d: %.9f" % (self.iter_id, batch_noo_loss))

                if self.iou_with_ground_truth and self.iter_id % self.display_step == 0:
                    ''' Calculate batch object loss '''
                    batch_o_loss = sess.run(tf.reduce_mean(iou_predict_truth),
                                          feed_dict={self.x: batch_xs,
                                                     self.y: batch_ys})
                    print("Average IOU with ground for iteration %d: %.9f" % (self.iter_id, batch_o_loss))

                if self.display_coords is True and self.iter_id % self.display_step == 0:
                    ''' Caculate predicted coordinates '''
                    coords_predict = sess.run(batch_pred_coords,
                                              feed_dict={self.x: batch_xs,
                                                         self.y: batch_ys})
                    print("predicted coords:" + str(coords_predict[0]))
                    print("ground truth coords:" + str(batch_ys[0]))

                ''' Save model '''
                if self.iter_id % self.save_step == 1:
                    self.saver.save(sess, self.rolo_current_save)
                    print("\n Model saved in file: %s" % self.rolo_current_save)

                ''' Validation '''
                if self.validate == True and self.iter_id % self.validate_step == 0 and self.iter_id > 0:
                    # Run validation set

                    dataset_loss = self.test(sess, total_loss, validation_set_loader, batch_pred_feats, batch_pred_coords, batch_pred_confs, self.final_state)

                    ''' Early-stop regularization '''
                    if dataset_loss <= dataset_loss_best:
                        dataset_loss_best = dataset_loss
                        self.saver.save(sess, self.rolo_weights_file)
                        print("\n Better Model saved in file: %s" % self.rolo_weights_file)

                    ''' Write summary for tensorboard '''
                    summary = sess.run(summary_op, feed_dict={self.x: batch_xs,
                                                              self.y: batch_ys})
                    test_writer.add_summary(summary, self.iter_id)
            print("Average total loss %f" % np.mean(epoch_loss))
        return


    def test(self, sess, loss, batch_loader, batch_pred_feats, batch_pred_coords, batch_pred_confs, final_state):
        loss_dataset_total = 0
        #TODO: put outputs somewhere
        batch_states = np.zeros((self.batchsize, 2*self.len_vec))
        iou_predict_truth, intersection = self.iou(batch_pred_coords, self.y[:,0:4])
        false_positives = 0
        true_positives = 0
        false_negatives = 0
        true_negatives = 0
        frames = 0
        total_prediction_time = 0.0

        # TODO: move this
        output_path = os.path.join('rolo_loc_test/')
        image_output_dir = './results'
        if not os.path.exists(output_path):
            os.makedirs(output_path)
        if not os.path.exists(image_output_dir):
            os.makedirs(image_output_dir)

        iou_averages = []
        intersection_averages =[]
        print("Starting test batches")
        for batch_id in range(len(batch_loader.batches)):
            xs, ys, im_paths = batch_loader.load_batch(batch_id)

            frames += len(xs)
            loss_seq_total = 0

            init_state_zeros = np.zeros((len(xs), 2*xs[0].shape[-1]))
            start=dt.datetime.now()

            pred_location, pred_confs = sess.run([batch_pred_coords, batch_pred_confs],feed_dict={self.x: xs, self.y: ys})

            end=dt.datetime.now()
            total_prediction_time += (end-start).microseconds / 1e6

            iou_ground_truth, intersection_predicted = sess.run([iou_predict_truth, intersection],
                                  feed_dict={self.x: xs,
                                             self.y: ys})

            ious = []
            intersections = []
            # TODO: clean this up, remove logging
            for i, loc in enumerate(pred_location):
                img = cv2.imread(im_paths[i])
                # TODO: this is a hack to get the video basename :(
                base_name = im_paths[i].split("/")[-3]
                width, height = img.shape[1::-1]

                if self.output_validation_images:
                    yolo_box = locations_normal(width, height, xs[i][-1][self.len_feat+1:-1]*int(xs[i][-1][-1] > self.confidence_detection_threshold)) #times the confidence to zero out a non-confident bounding box
                    rolo_box = locations_normal(width, height, pred_location[i] * int(pred_confs[i] > self.confidence_detection_threshold))
                    img_result = debug_3_locations(img, locations_normal(width, height, ys[i]), yolo_box, rolo_box)
                    cv2.imwrite('./results/%s_%d_%d.jpg' %(base_name, batch_id, i), img_result)
                """
                print("predicted")
                print(pred_location[i])
                print("gold")
                print(ys[i])
                print("confidence")
                print(pred_confs[i])
                print("numpy iou")
                print(iou(pred_location[i], ys[i]))
                print("tf iou")
                print(iou_ground_truth[i])
                """
                if pred_confs[i] > self.confidence_detection_threshold:
                    # we have a poisitive detection
                    if np.count_nonzero(ys[i]) == 0:
                        # We have no bounding box in the gold
                        false_positives += 1
                    else:
                        ious.append(iou_ground_truth[i])
                        intersections.append(intersection_predicted[i])
                        true_positives += 1
                else:
                    # No detection
                    if np.count_nonzero(ys[i]) == 0:
                        true_negatives += 1
                    else:
                        false_negatives += 1

            init_state = init_state_zeros

            batch_loss = sess.run(loss,
                                  feed_dict={self.x: xs,
                                             self.y: ys})


            loss_seq_total += batch_loss

            loss_seq_avg = loss_seq_total / xs.shape[0]
            if ious:
                iou_seq_avg = np.mean(ious)
                iou_averages.append(iou_seq_avg)

            loss_dataset_total += loss_seq_avg
            if intersections:
                intersection_averages.append(np.mean(intersections))

        print('Total loss of Dataset: %f \n', loss_dataset_total)
        print('Average iou with ground truth: %f \n', np.mean(iou_averages))
        print('Average intersection with ground truth: %f \n', np.mean(intersection_averages))
        print('False Positives %d', false_positives)
        print('True Positives %d', true_positives)
        print('True Negatives %d', true_negatives)
        print('False Negatives %d', false_negatives)
        print('Total Number of Frames %d', frames)
        print('Total Prediction Computation Time %f seconds', total_prediction_time)
        return loss_dataset_total

    def ROLO(self):
        print("Initializing ROLO")
        self.train()
        print("Training Completed")

'''----------------------------------------main-----------------------------------------------------'''
def main(argvs):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", type=int, default=1, help="number of layers of LSTM to use, defaults to 1")
    parser.add_argument("-b", action='store_true', default=False, help="Whether to use a bidirectional LSTM")
    args = parser.parse_args()

    ROLO_TF({'num_layers' : args.n, "bidirectional" : args.b})

if __name__ == "__main__":
    main(' ')
