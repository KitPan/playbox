import theano.tensor as t

def cropExtremes(x) :
    # protect the loss function against producing NaNs/Inf
    return t.clip(x, 1e-7, 1.0 - 1e-7)

def crossEntropyLoss (p, q, axis=None, crop=True):
    ''' for these purposes this is equivalent to Negative Log Likelihood
        this is the average of all cross-entropies in our guess
        p    : the target value
        q    : the current estimate
        axis : the axis in which to sum across -- used for multi-dimensional
        crop :
    '''
    if crop : q = cropExtremes(q)
    return t.mean(t.sum(t.nnet.binary_crossentropy(q, p), axis=axis))

def meanSquaredLoss (p, q) :
    ''' for these purposes this is equivalent to Negative Log Likelihood
        p    : the target value
        q    : the current estimate
    '''
    return t.mean((q - p) ** 2)

def leastAbsoluteDeviation(a, batchSize=None, scaleFactor=1.) :
    '''L1-norm provides 'Least Absolute Deviation' --
       built for sparse outputs and is resistent to outliers

       a           : input matrix
       batchSize   : number of inputs in the batchs
       scaleFactor : scale factor for the regularization
    '''
    if not isinstance(a, list) :
        a = [a]
    absSum = sum([t.sum(t.abs_(arr)) for arr in a])

    if batchSize is not None :
        return t.mean(absSum // batchSize) * scaleFactor
    else :
        return absSum * scaleFactor

def leastSquares(a, batchSize=None, scaleFactor=1.) :
    '''L2-norm provides 'Least Squares' --
       built for dense outputs and is computationally stable at small errors

       a           : input matrix
       batchSize   : number of inputs in the batchs
       scaleFactor : scale factor for the regularization

       NOTE: a decent scale factor may be the 1. / numNeurons
    '''
    if not isinstance(a, list) :
        a = [a]
    sqSum = sum([t.sum(arr ** 2) for arr in a])

    if batchSize is not None :
        return t.mean(sqSum // batchSize) * scaleFactor
    else :
        return sqSum * scaleFactor

def computeJacobian(a, wrt, batchSize, inputSize, numNeurons) :
    '''Compute a jacobian for the matrix 'out' with respect to 'wrt'.

       This is the first order partials of the output with respect to the 
       weights. This produces a matrix the same size as the input that
       produced the output vector.

       a          : The output matrix for the layer (batchSize, numNeurons)
       wrt        : Matrix used to generate 'mat'. This is usually the weight
                    matrix. (inputSize, numNeurons)
       batchSize  : Number of inputs in the batch
       inputSize  : Size of each input
       numNeurons : Number of neurons in the weight matrix
       return     : (batchSize, inputSize)
    '''
    aReshape = (batchSize, 1, numNeurons)
    wrtReshape = (1, inputSize, numNeurons)
    return t.reshape(a * (1 - a), aReshape) * t.reshape(wrt, wrtReshape)
